# -*- coding: utf-8 -*-
"""arXiv API 客户端。

职责
----
1. 构造带时间窗口的检索式（``submittedDate:[start TO end]``）；
2. 带限流与指数退避重试地抓取 Atom XML；
3. 解析 XML 为 :class:`Paper` 数据类，并做清洗（去换行、去多余空白）；
4. 提供客户端关键词匹配，用于「宽召回 + 精筛」的第二阶段。

注意：arXiv 官方 API 不支持 ``days=7`` 这类相对时间参数，
必须由调用方把「最近 X 天」换算成 UTC 的绝对时间区间。
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import requests

from .config import (
    ARXIV_API_URL,
    ARXIV_MAX_RETRIES,
    ARXIV_MIN_INTERVAL,
    ARXIV_PAGE_SIZE,
    HTTP_TIMEOUT,
    MAX_RESULTS_HARD_CAP,
)

logger = logging.getLogger(__name__)

# 少带一个 UA，arXiv 可能直接返回 403
USER_AGENT = (
    "NN-Literature-Tracker/1.0 (course project; Python-requests)"
)

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
NS = {"atom": ATOM_NS, "arxiv": ARXIV_NS, "opensearch": OPENSEARCH_NS}


class ArxivError(RuntimeError):
    """arXiv 抓取或解析失败。调用方应捕获它并给用户友好提示。"""


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------
@dataclass
class Paper:
    """一篇 arXiv 论文的规范化表示。字段与 SQLite ``papers`` 表一一对应。"""

    arxiv_id: str
    title: str
    abstract: str
    authors: str
    published: str          # UTC ISO8601，形如 2026-11-20T18:00:00Z
    updated: str
    abs_url: str
    pdf_url: str
    primary_category: str
    all_categories: str     # 逗号分隔
    comment: str
    journal_ref: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    @property
    def searchable_text(self) -> str:
        """用于关键词匹配的小写文本（标题 + 摘要 + 作者备注）。"""
        return f"{self.title} {self.abstract} {self.comment}".lower()


# --------------------------------------------------------------------------
# 检索式构造
# --------------------------------------------------------------------------
def build_date_range(days: int, now: Optional[datetime] = None) -> Tuple[str, datetime, datetime]:
    """把「最近 X 天」换算成 arXiv 需要的 ``[YYYYMMDDHHMM TO YYYYMMDDHHMM]``。

    时间统一使用 UTC——arXiv 的 submittedDate 字段是 UTC，用本地时间会
    导致边缘日期漏检/多检。
    """
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    else:
        end = end.astimezone(timezone.utc)

    days = max(1, int(days))
    start = end - timedelta(days=days)

    fmt = "%Y%m%d%H%M"
    return f"[{start.strftime(fmt)} TO {end.strftime(fmt)}]", start, end


def build_search_query(arxiv_cat: str, days: int, now: Optional[datetime] = None) -> str:
    """构造 arXiv search_query，例如::

        cat:cs.CV AND submittedDate:[202611160000 TO 202611231500]
    """
    date_range, _, _ = build_date_range(days, now)
    return f"cat:{arxiv_cat} AND submittedDate:{date_range}"


def build_custom_query(term: str, days: int, now: Optional[datetime] = None) -> str:
    """按用户自填的英文主题词构造检索式，例如::

        (ti:"battery lifetime prediction" OR abs:"battery lifetime prediction")
        AND submittedDate:[202611160000 TO 202611231500]

    用 ``ti:`` 或 ``abs:`` 而不是 ``all:``，是为了避开作者名/评论里的无关命中。
    主题词里若带英文双引号会破坏检索式语法，这里直接剔除。
    """
    date_range, _, _ = build_date_range(days, now)
    clean = " ".join((term or "").replace('"', " ").split())
    if not clean:
        raise ArxivError("自定义主题词为空，无法构造检索式")
    return f'(ti:"{clean}" OR abs:"{clean}") AND submittedDate:{date_range}'


# --------------------------------------------------------------------------
# 限流
# --------------------------------------------------------------------------
_last_call_ts: float = 0.0


def _throttle() -> None:
    """保证两次 arXiv 请求至少间隔 ``ARXIV_MIN_INTERVAL`` 秒。"""
    global _last_call_ts
    elapsed = time.monotonic() - _last_call_ts
    wait = ARXIV_MIN_INTERVAL - elapsed
    if wait > 0:
        logger.debug("arXiv 限流等待 %.2f 秒", wait)
        time.sleep(wait)
    _last_call_ts = time.monotonic()


# --------------------------------------------------------------------------
# 抓取
# --------------------------------------------------------------------------
def fetch_raw(search_query: str, start: int = 0, max_results: int = 50) -> str:
    """调用 arXiv API 并返回原始 XML 文本。

    重试策略：
        * 网络异常 / 超时 -> 指数退避重试（2s, 4s, 8s 封顶）
        * HTTP 429 或 5xx -> 同上，若响应带 ``Retry-After`` 则优先遵循
        * 其他 4xx（如检索式写错）-> 立即抛错，重试也没用
    """
    params = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    last_error: Optional[Exception] = None

    for attempt in range(1, ARXIV_MAX_RETRIES + 1):
        _throttle()
        try:
            resp = requests.get(
                ARXIV_API_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            last_error = exc
            logger.warning(
                "arXiv 请求异常（第 %d/%d 次）: %s", attempt, ARXIV_MAX_RETRIES, exc
            )
            time.sleep(min(2 ** attempt, 8))
            continue

        if resp.status_code == 200:
            return resp.text

        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            last_error = ArxivError(f"arXiv 返回 HTTP {resp.status_code}")
            sleep_s = min(2 ** attempt, 8)
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                sleep_s = max(sleep_s, float(retry_after))
            logger.warning(
                "arXiv HTTP %s（第 %d/%d 次），%.1f 秒后重试",
                resp.status_code, attempt, ARXIV_MAX_RETRIES, sleep_s,
            )
            time.sleep(sleep_s)
            continue

        # 400/403 等：重试无意义，直接失败
        raise ArxivError(
            f"arXiv 返回 HTTP {resp.status_code}，检索式可能不合法：{search_query!r}"
        )

    raise ArxivError(
        f"arXiv 连续 {ARXIV_MAX_RETRIES} 次请求失败，最后一次错误：{last_error}"
    )


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
def _clean(text: Optional[str]) -> str:
    """压缩空白：XML 里的换行与缩进会污染标题和摘要。"""
    if not text:
        return ""
    return " ".join(text.split())


_VERSION_RE = re.compile(r"v\d+$")
_ABS_ID_RE = re.compile(r"/abs/(.+)$")


def _extract_arxiv_id(raw_id: str) -> str:
    """``http://arxiv.org/abs/2611.01234v2`` -> ``2611.01234``。"""
    raw_id = (raw_id or "").strip()
    match = _ABS_ID_RE.search(raw_id)
    if match:
        raw_id = match.group(1)
    return _VERSION_RE.sub("", raw_id)


def _norm_datetime(raw: str) -> str:
    """统一时间格式为 ``YYYY-MM-DDTHH:MM:SSZ``，便于 SQLite 字符串比较。"""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:19]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_atom(xml_text: str) -> List[Paper]:
    """把 Atom XML 解析成 Paper 列表。

    对单条 entry 的解析失败采取「跳过并记日志」而不是整体失败——
    一篇脏数据不该让整次抓取崩掉。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ArxivError(f"arXiv 返回的 XML 无法解析：{exc}") from exc

    papers: List[Paper] = []

    for entry in root.findall("atom:entry", NS):
        try:
            raw_id = _clean(entry.findtext("atom:id", default="", namespaces=NS))
            # arXiv 的查询错误也会以 entry 形式返回，需要剔除
            if "/api/errors" in raw_id:
                logger.warning("arXiv 返回错误条目：%s", raw_id)
                continue

            arxiv_id = _extract_arxiv_id(raw_id)
            if not arxiv_id:
                continue

            title = _clean(entry.findtext("atom:title", default="", namespaces=NS))
            abstract = _clean(entry.findtext("atom:summary", default="", namespaces=NS))
            if not title:
                continue

            authors = ", ".join(
                _clean(a.findtext("atom:name", default="", namespaces=NS))
                for a in entry.findall("atom:author", NS)
            )

            published = _norm_datetime(
                entry.findtext("atom:published", default="", namespaces=NS)
            )
            updated = _norm_datetime(
                entry.findtext("atom:updated", default="", namespaces=NS)
            )

            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

            for link in entry.findall("atom:link", NS):
                href = link.get("href") or ""
                if link.get("title") == "pdf" and href:
                    pdf_url = href
                elif link.get("rel") == "alternate" and href:
                    abs_url = href

            primary_el = entry.find("arxiv:primary_category", NS)
            primary_category = (
                primary_el.get("term", "") if primary_el is not None else ""
            )

            all_categories = ",".join(
                cat.get("term", "") for cat in entry.findall("atom:category", NS)
            )

            comment = _clean(entry.findtext("arxiv:comment", default="", namespaces=NS))
            journal_ref = _clean(
                entry.findtext("arxiv:journal_ref", default="", namespaces=NS)
            )

            papers.append(
                Paper(
                    arxiv_id=arxiv_id,
                    title=title,
                    abstract=abstract,
                    authors=authors,
                    published=published,
                    updated=updated,
                    abs_url=abs_url,
                    pdf_url=pdf_url,
                    primary_category=primary_category,
                    all_categories=all_categories,
                    comment=comment,
                    journal_ref=journal_ref,
                )
            )
        except Exception as exc:  # 单条解析失败不影响整体
            logger.warning("解析单条 arXiv entry 失败，已跳过：%s", exc)
            continue

    return papers


def fetch_papers(
    arxiv_cat: str = "",
    days: int = 7,
    max_results: int = 30,
    now: Optional[datetime] = None,
    search_query: Optional[str] = None,
) -> Tuple[List[Paper], str]:
    """抓取某个 arXiv 类目（或自定义检索式）下最近 ``days`` 天的论文。

    Args:
        arxiv_cat: arXiv 类目；当 ``search_query`` 给出时可留空。
        search_query: 直接指定完整检索式（自定义主题词走这条路）。

    Returns:
        (papers, search_query)：同时把检索式返回出去，方便写进抓取日志与 TDD 演示。
    """
    query = search_query or build_search_query(arxiv_cat, days, now=now)
    target = min(max(1, int(max_results)), MAX_RESULTS_HARD_CAP)

    collected: List[Paper] = []
    seen = set()
    offset = 0

    while len(collected) < target:
        page_size = min(ARXIV_PAGE_SIZE, target - len(collected))
        xml_text = fetch_raw(query, start=offset, max_results=page_size)
        page = parse_atom(xml_text)

        if not page:
            logger.info("检索式 %r 在 offset=%d 处已无更多结果", query, offset)
            break

        for paper in page:
            if paper.arxiv_id not in seen:
                seen.add(paper.arxiv_id)
                collected.append(paper)

        if len(page) < page_size:
            break
        offset += page_size

    return collected[:target], query


# --------------------------------------------------------------------------
# 第二阶段：客户端关键词精筛
# --------------------------------------------------------------------------
def keyword_match(paper: Paper, keywords: Sequence[str]) -> bool:
    """标题/摘要/备注中是否出现任一领域词。

    ``keywords`` 为空表示不做过滤（该类目本身就是该方向）。
    """
    if not keywords:
        return True
    text = paper.searchable_text
    return any(kw.lower() in text for kw in keywords)
