# -*- coding: utf-8 -*-
"""SQLite 持久化层。

表设计
------
``papers``        论文正文信息（主键 arxiv_id，天然去重）
``paper_groups``  论文 ↔ 神经网络功能方向 的多对多关系
``extractions``   LLM 结构化提取结果（含解析状态与原始响应，便于审计）
``fetch_log``     每次抓取的可观测记录（检索式、条数、错误）

之所以把「论文」与「提取结果」分两张表，是为了满足防幻觉要求：
即使 LLM 这一步彻底失败，论文本身仍然可以展示（降级为显示原始摘要），
不会因为结构化提取失败而让整条数据消失。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .config import DB_PATH, ensure_dirs

logger = logging.getLogger(__name__)

# 视作「已完成提取」，下次不再重复调用 LLM（省钱）
DONE_STATUS = ("ok", "repaired", "fallback")

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id         TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    abstract         TEXT,
    authors          TEXT,
    published        TEXT,
    updated          TEXT,
    abs_url          TEXT,
    pdf_url          TEXT,
    primary_category TEXT,
    all_categories   TEXT,
    comment          TEXT,
    journal_ref      TEXT,
    keyword_hit      INTEGER DEFAULT 0,
    fetched_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published);

CREATE TABLE IF NOT EXISTS paper_groups (
    arxiv_id     TEXT NOT NULL,
    category_key TEXT NOT NULL,
    PRIMARY KEY (arxiv_id, category_key)
);

CREATE INDEX IF NOT EXISTS idx_groups_category ON paper_groups(category_key);

CREATE TABLE IF NOT EXISTS extractions (
    arxiv_id                 TEXT PRIMARY KEY,
    one_line_contribution    TEXT,
    datasets_methods         TEXT,
    code_open_source         TEXT,
    code_url                 TEXT,
    evidence                 TEXT,
    model                    TEXT,
    parse_status             TEXT,
    raw_response             TEXT,
    extracted_at             TEXT
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category_key TEXT,
    days         INTEGER,
    search_query TEXT,
    fetched      INTEGER,
    kept         INTEGER,
    ok           INTEGER,
    error        TEXT,
    created_at   TEXT
);

-- 摘要译文缓存：同一篇同一目标语言只翻一次，避免重复计费
CREATE TABLE IF NOT EXISTS translations (
    arxiv_id    TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    content     TEXT,
    model       TEXT,
    created_at  TEXT,
    PRIMARY KEY (arxiv_id, target_lang)
);

-- 中文检索词翻译缓存：词典未命中时才写入
CREATE TABLE IF NOT EXISTS keyword_cache (
    src        TEXT PRIMARY KEY,
    dst        TEXT,
    source     TEXT,
    created_at TEXT
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cutoff_iso(days: int) -> str:
    """最近 X 天的时间下界（UTC ISO8601，可直接与 published 做字符串比较）。"""
    days = max(1, int(days))
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


@contextmanager
def get_conn():
    """自动 commit / rollback / close 的连接上下文。"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.debug("数据库初始化完成: %s", DB_PATH)


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------
def upsert_paper(paper: Dict[str, Any], category_key: str, keyword_hit: bool) -> bool:
    """插入或更新一篇论文，并登记它属于哪个功能方向。

    Returns:
        True 表示这是一篇新论文（此前库里没有）。
    """
    arxiv_id = paper["arxiv_id"]

    sql = """
    INSERT INTO papers (
        arxiv_id, title, abstract, authors, published, updated,
        abs_url, pdf_url, primary_category, all_categories,
        comment, journal_ref, keyword_hit, fetched_at
    ) VALUES (
        :arxiv_id, :title, :abstract, :authors, :published, :updated,
        :abs_url, :pdf_url, :primary_category, :all_categories,
        :comment, :journal_ref, :keyword_hit, :fetched_at
    )
    ON CONFLICT(arxiv_id) DO UPDATE SET
        title            = excluded.title,
        abstract         = excluded.abstract,
        authors          = excluded.authors,
        updated          = excluded.updated,
        comment          = excluded.comment,
        journal_ref      = excluded.journal_ref,
        all_categories   = excluded.all_categories,
        -- 同一篇论文可能被多个方向命中；只要任一次命中关键词，就保留 1
        keyword_hit      = max(papers.keyword_hit, excluded.keyword_hit),
        fetched_at       = excluded.fetched_at
    """
    params = dict(paper)
    params["keyword_hit"] = 1 if keyword_hit else 0
    params["fetched_at"] = utc_now_iso()

    with get_conn() as conn:
        existed = (
            conn.execute(
                "SELECT 1 FROM papers WHERE arxiv_id = ?", (arxiv_id,)
            ).fetchone()
            is not None
        )
        conn.execute(sql, params)
        conn.execute(
            "INSERT OR IGNORE INTO paper_groups (arxiv_id, category_key) VALUES (?, ?)",
            (arxiv_id, category_key),
        )
    return not existed


def save_extraction(arxiv_id: str, result: Dict[str, Any]) -> None:
    """保存一次结构化提取结果（幂等覆盖）。"""
    datasets = result.get("datasets_methods") or []
    if not isinstance(datasets, list):
        datasets = [str(datasets)]

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO extractions (
                arxiv_id, one_line_contribution, datasets_methods, code_open_source,
                code_url, evidence, model, parse_status, raw_response, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(arxiv_id) DO UPDATE SET
                one_line_contribution = excluded.one_line_contribution,
                datasets_methods      = excluded.datasets_methods,
                code_open_source      = excluded.code_open_source,
                code_url              = excluded.code_url,
                evidence              = excluded.evidence,
                model                 = excluded.model,
                parse_status          = excluded.parse_status,
                raw_response          = excluded.raw_response,
                extracted_at          = excluded.extracted_at
            """,
            (
                arxiv_id,
                result.get("one_line_contribution"),
                json.dumps(datasets, ensure_ascii=False),
                result.get("code_open_source", "unknown"),
                result.get("code_url"),
                result.get("evidence"),
                result.get("model"),
                result.get("parse_status", "ok"),
                (result.get("raw_response") or "")[:4000],
                utc_now_iso(),
            ),
        )


def save_extraction_failure(arxiv_id: str, error: str) -> None:
    """记录失败状态。标记为 failed 的论文下次刷新还会重试。"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO extractions (
                arxiv_id, one_line_contribution, datasets_methods, code_open_source,
                code_url, evidence, model, parse_status, raw_response, extracted_at
            ) VALUES (?, NULL, '[]', 'unknown', NULL, NULL, NULL, 'failed', ?, ?)
            ON CONFLICT(arxiv_id) DO UPDATE SET
                parse_status = 'failed',
                raw_response = excluded.raw_response,
                extracted_at = excluded.extracted_at
            """,
            (arxiv_id, (error or "")[:4000], utc_now_iso()),
        )


def log_fetch(
    category_key: str,
    days: int,
    search_query: str,
    fetched: int,
    kept: int,
    ok: bool,
    error: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO fetch_log (
                category_key, days, search_query, fetched, kept, ok, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category_key, int(days), search_query,
                int(fetched), int(kept), 1 if ok else 0,
                (error or "")[:1000], utc_now_iso(),
            ),
        )


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------
def has_extraction(arxiv_id: str) -> bool:
    """是否已有可用的结构化结果（失败状态不算，需要重试）。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT parse_status FROM extractions WHERE arxiv_id = ?", (arxiv_id,)
        ).fetchone()
    return bool(row and row["parse_status"] in DONE_STATUS)


def query_papers(
    keyword: str = "",
    open_source: str = "all",
    category_key: str = "all",
    days: Optional[int] = None,
    limit: int = 200,
    keywords: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """看板主查询：联表取论文 + 结构化字段，支持关键词/开源状态/方向/时间过滤。

    Args:
        keyword: 原始检索词（可能是中文）。
        keywords: 附加检索词（通常是中文关键词自动翻译出的英文词），
            与 ``keyword`` 之间是 **OR** 关系——命中任意一个就返回。
    """
    sql = [
        "SELECT p.arxiv_id, p.title, p.authors, p.abstract, p.published, p.updated,",
        "       p.abs_url, p.pdf_url, p.primary_category, p.all_categories,",
        "       p.comment, p.keyword_hit, p.fetched_at,",
        "       e.one_line_contribution, e.datasets_methods, e.code_open_source,",
        "       e.code_url, e.evidence, e.parse_status, e.model, e.extracted_at,",
        "       (SELECT GROUP_CONCAT(g.category_key, ',') FROM paper_groups g",
        "         WHERE g.arxiv_id = p.arxiv_id) AS category_keys",
        "FROM papers p",
        "LEFT JOIN extractions e ON e.arxiv_id = p.arxiv_id",
        "WHERE 1 = 1",
    ]
    params: List[Any] = []

    # ---- 关键词：原始词 + 自动翻译出的英文词，OR 组合 ----
    terms: List[str] = []
    raw_keyword = (keyword or "").strip()
    if raw_keyword:
        terms.append(raw_keyword)
    for extra in keywords or ():
        extra = (extra or "").strip()
        if extra and extra not in terms:
            terms.append(extra)

    if terms:
        field_clause = (
            "(p.title LIKE ? OR p.abstract LIKE ?"
            " OR IFNULL(e.one_line_contribution, '') LIKE ?"
            " OR IFNULL(e.datasets_methods, '') LIKE ?)"
        )
        sql.append(" AND (" + " OR ".join([field_clause] * len(terms)) + ")")
        for term in terms:
            like = f"%{term}%"
            params.extend([like, like, like, like])

    if open_source and open_source != "all":
        if open_source == "unknown":
            sql.append(" AND (e.code_open_source IS NULL OR e.code_open_source = 'unknown')")
        else:
            sql.append(" AND e.code_open_source = ?")
            params.append(open_source)

    if category_key and category_key != "all":
        sql.append(
            " AND EXISTS (SELECT 1 FROM paper_groups g2"
            "             WHERE g2.arxiv_id = p.arxiv_id AND g2.category_key = ?)"
        )
        params.append(category_key)

    if days:
        sql.append(" AND p.published >= ?")
        params.append(cutoff_iso(days))

    sql.append(" ORDER BY p.published DESC LIMIT ?")
    params.append(max(1, int(limit)))

    with get_conn() as conn:
        rows = conn.execute(" ".join(sql), params).fetchall()

    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    raw = data.get("datasets_methods")
    if raw:
        try:
            parsed = json.loads(raw)
            data["datasets_methods"] = parsed if isinstance(parsed, list) else [str(parsed)]
        except (json.JSONDecodeError, TypeError):
            # 脏数据兜底：当作空列表，界面显示「未提取」
            data["datasets_methods"] = []
    else:
        data["datasets_methods"] = []
    data["category_keys"] = [
        k for k in (data.get("category_keys") or "").split(",") if k
    ]
    return data


# --------------------------------------------------------------------------
# 译文缓存
# --------------------------------------------------------------------------
def get_translation(arxiv_id: str, target_lang: str) -> Optional[Dict[str, Any]]:
    """取已缓存的译文；没有则返回 None。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT content, model, created_at FROM translations"
            " WHERE arxiv_id = ? AND target_lang = ?",
            (arxiv_id, target_lang),
        ).fetchone()
    return dict(row) if row else None


def save_translation(
    arxiv_id: str, target_lang: str, content: str, model: str = ""
) -> None:
    """写入/覆盖译文缓存。"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO translations (arxiv_id, target_lang, content, model, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(arxiv_id, target_lang) DO UPDATE SET
                content    = excluded.content,
                model      = excluded.model,
                created_at = excluded.created_at
            """,
            (arxiv_id, target_lang, content, model, utc_now_iso()),
        )


def get_keyword_cache(src: str) -> Optional[Dict[str, Any]]:
    """取中文检索词的翻译缓存。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT dst, source, created_at FROM keyword_cache WHERE src = ?", (src,)
        ).fetchone()
    return dict(row) if row else None


def save_keyword_cache(src: str, dst: str, source: str = "llm") -> None:
    """写入中文检索词翻译缓存。"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO keyword_cache (src, dst, source, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(src) DO UPDATE SET
                dst        = excluded.dst,
                source     = excluded.source,
                created_at = excluded.created_at
            """,
            (src, dst, source, utc_now_iso()),
        )


def get_overview() -> Dict[str, Any]:
    """看板顶部的统计数字。"""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM papers").fetchone()["c"]
        structured = conn.execute(
            "SELECT COUNT(*) AS c FROM extractions WHERE parse_status IN ('ok','repaired','fallback')"
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT COUNT(*) AS c FROM extractions WHERE parse_status = 'failed'"
        ).fetchone()["c"]
        open_src = conn.execute(
            "SELECT COUNT(*) AS c FROM extractions WHERE code_open_source = 'yes'"
        ).fetchone()["c"]
        last_row = conn.execute(
            "SELECT MAX(created_at) AS t FROM fetch_log"
        ).fetchone()

    return {
        "total": total,
        "structured": structured,
        "failed": failed,
        "open_source": open_src,
        "last_fetch": (last_row["t"] if last_row else None) or "—",
    }


def category_counts() -> Dict[str, int]:
    """每个功能方向当前有多少篇论文（用于侧边栏提示）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category_key, COUNT(*) AS c FROM paper_groups GROUP BY category_key"
        ).fetchall()
    return {r["category_key"]: r["c"] for r in rows}


def get_fetch_log(limit: int = 20) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM fetch_log ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(r) for r in rows]


def clear_all() -> None:
    """清空所有业务数据（保留表结构）。"""
    with get_conn() as conn:
        for table in (
            "extractions", "paper_groups", "papers", "fetch_log",
            "translations", "keyword_cache",
        ):
            conn.execute(f"DELETE FROM {table}")  # 表名为常量，不存在注入风险
    logger.info("数据库已清空")
