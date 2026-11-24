# -*- coding: utf-8 -*-
"""流水线编排：抓取 → 关键词精筛 → 入库 → LLM 结构化提取。

设计要点
--------
* **职责单一**：本模块只做编排，不关心 HTTP 细节、Prompt 细节与 SQL 细节，
  这样每一层都能单独测试（见 技术设计文档.md 第 5 节）。
* **局部失败不扩散**：某个方向抓取失败、某篇论文提取失败，都只记进
  ``stats.errors`` 并继续处理剩余数据，保证一次刷新能拿到「尽可能多」的结果。
* **增量执行**：已成功结构化的论文不会重复调用 LLM，节省 token 与时间。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .arxiv_client import (
    ArxivError,
    Paper,
    build_custom_query,
    fetch_papers,
    keyword_match,
)
from .categories import ALL_KEYS, get_category
from .config import LLM_SLEEP_BETWEEN_CALLS
from .llm_extractor import LLMExtractor
from .storage import (
    has_extraction,
    init_db,
    log_fetch,
    save_extraction,
    save_extraction_failure,
    upsert_paper,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]

# 抓取阶段占 40% 进度，结构化阶段占 60%（抓取有 3 秒限流，通常更慢）
FETCH_PROGRESS_SHARE = 0.40


@dataclass
class PipelineStats:
    """一次刷新任务的执行结果，直接用于界面展示与日志。"""

    categories: int = 0
    fetched: int = 0             # arXiv 返回的原始条数
    kept: int = 0                # 通过精筛并入/更新的条数
    new_papers: int = 0          # 其中真正新增的
    extracted_ok: int = 0        # 一次解析成功
    extracted_repaired: int = 0  # 重试后成功
    extracted_fallback: int = 0  # 降级（保留原文）
    extract_failed: int = 0      # 彻底失败，下次重试
    skipped_cached: int = 0      # 已提取过而跳过的
    llm_used: bool = False
    elapsed: float = 0.0
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)

    def summary(self) -> str:
        parts = [
            f"抓取 {self.fetched} 篇",
            f"入库 {self.kept} 篇（新增 {self.new_papers}）",
        ]
        if self.llm_used:
            parts.append(
                f"结构化成功 {self.extracted_ok + self.extracted_repaired}"
                f"（重试修复 {self.extracted_repaired}）"
            )
            if self.extracted_fallback:
                parts.append(f"降级 {self.extracted_fallback}")
            if self.extract_failed:
                parts.append(f"失败 {self.extract_failed}")
            if self.skipped_cached:
                parts.append(f"命中缓存跳过 {self.skipped_cached}")
        parts.append(f"耗时 {self.elapsed:.1f}s")
        return "，".join(parts)


@dataclass(frozen=True)
class _Job:
    """一次抓取任务：要么是预置方向（按类目），要么是用户自定义主题词（按检索式）。"""

    key: str
    name: str
    arxiv_cat: str = ""
    keywords: Tuple[str, ...] = ()
    query: str = ""      # 非空表示走自定义检索式


def _build_jobs(
    category_keys: Sequence[str],
    custom_topics: Optional[Sequence[Dict[str, str]]],
    days: int,
    errors: List[str],
) -> List[_Job]:
    """把「预置方向 + 自定义主题词」合并成统一的抓取任务列表。"""
    jobs: List[_Job] = []

    for key in category_keys:
        if not key:
            continue
        try:
            category = get_category(key)
        except KeyError as exc:
            errors.append(str(exc))
            continue
        jobs.append(
            _Job(
                key=category.key,
                name=category.name,
                arxiv_cat=category.arxiv_cat,
                keywords=category.keywords,
            )
        )

    for topic in custom_topics or ():
        label = (topic.get("label") or "").strip()
        term = (topic.get("term") or "").strip()
        if not term:
            errors.append(f"自定义主题词「{label or '未命名'}」没有英文译名，已跳过")
            continue
        key = topic.get("key") or f"自定义｜{label or term}"
        try:
            query = build_custom_query(term, days)
        except ArxivError as exc:
            errors.append(f"自定义主题词「{label or term}」：{exc}")
            continue
        jobs.append(_Job(key=key, name=label or term, keywords=(), query=query))

    return jobs


def _emit(progress: Optional[ProgressFn], pct: float, message: str) -> None:
    """安全地调用进度回调——界面回调写错不该让后台任务崩掉。"""
    if progress is None:
        return
    try:
        progress(max(0.0, min(1.0, pct)), message)
    except Exception as exc:  # pragma: no cover
        logger.debug("进度回调异常（已忽略）：%s", exc)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run_pipeline(
    category_keys: Sequence[str],
    days: int = 7,
    max_results_per_category: int = 30,
    use_llm: bool = True,
    progress: Optional[ProgressFn] = None,
    custom_topics: Optional[Sequence[Dict[str, str]]] = None,
) -> PipelineStats:
    """执行一次完整的文献追踪刷新。任何单点异常都不会让函数抛出。

    Args:
        category_keys: 预置功能方向的 key 列表。
        custom_topics: 用户自填的主题词，每项形如
            ``{"key": "自定义｜电池寿命预测", "label": "电池寿命预测",
               "term": "battery lifetime prediction"}``。
    """
    init_db()

    stats = PipelineStats()
    started = time.time()

    jobs = _build_jobs(category_keys, custom_topics, days, stats.errors)
    if not jobs:
        stats.errors.append("未选择任何功能方向，也没有可用的自定义主题词")
        _emit(progress, 1.0, "没有可抓取的目标")
        return stats
    stats.categories = len(jobs)

    # ------------------------------------------------------------------
    # 阶段一：按功能方向 / 自定义主题词抓取
    # ------------------------------------------------------------------
    candidates: List[Paper] = []

    for index, job in enumerate(jobs):
        key = job.key
        category = job   # 统一用 job 的属性，避免两套分支

        _emit(
            progress,
            FETCH_PROGRESS_SHARE * index / len(jobs),
            f"正在抓取「{category.name}」近 {days} 天的论文…",
        )

        try:
            if job.query:
                # 自定义主题词：完整检索式已由 build_custom_query 生成
                papers, query = fetch_papers(
                    days=days,
                    max_results=max_results_per_category,
                    search_query=job.query,
                )
            else:
                papers, query = fetch_papers(
                    category.arxiv_cat, days, max_results_per_category
                )
        except ArxivError as exc:
            logger.error("方向 %s 抓取失败：%s", key, exc)
            stats.errors.append(f"{category.name}：{exc}")
            log_fetch(key, days, "", 0, 0, ok=False, error=str(exc))
            continue
        except Exception as exc:  # 兜住任何未预期异常，保证其它方向继续
            logger.exception("方向 %s 抓取出现未预期异常", key)
            stats.errors.append(f"{category.name}：{exc}")
            log_fetch(key, days, "", 0, 0, ok=False, error=str(exc))
            continue

        stats.fetched += len(papers)

        # 第二阶段精筛：标题/摘要命中领域词才算该方向的论文
        matched = [p for p in papers if keyword_match(p, category.keywords)]
        if not matched and papers:
            # 兜底：关键词过于严格时退回该类目全部结果，避免看板空白
            logger.info("方向 %s 关键词命中 0 条，回退为类目全量结果", key)
            matched = papers

        kept = 0
        for paper in matched:
            hit = keyword_match(paper, category.keywords)
            if upsert_paper(paper.to_dict(), key, keyword_hit=hit):
                stats.new_papers += 1
            kept += 1

        stats.kept += kept
        candidates.extend(matched)
        log_fetch(key, days, query, len(papers), kept, ok=True)

    # 跨方向去重（同一篇论文可能同时命中 cs.LG 与 cs.CL）
    unique: Dict[str, Paper] = {}
    for paper in candidates:
        unique.setdefault(paper.arxiv_id, paper)

    # ------------------------------------------------------------------
    # 阶段二：LLM 结构化提取
    # ------------------------------------------------------------------
    if not use_llm:
        _emit(progress, 1.0, "已跳过 LLM 结构化提取（仅完成抓取）")
        stats.elapsed = time.time() - started
        return stats

    extractor = LLMExtractor()
    if not extractor.available:
        stats.errors.append(
            "未配置可用的 DEEPSEEK_API_KEY，已跳过结构化提取；"
            "看板仍会展示论文与其原始摘要。"
        )
        _emit(progress, 1.0, "未配置 API Key，仅完成抓取")
        stats.elapsed = time.time() - started
        return stats

    stats.llm_used = True
    pending = [p for p in unique.values() if not has_extraction(p.arxiv_id)]
    stats.skipped_cached = len(unique) - len(pending)

    total = len(pending)
    for index, paper in enumerate(pending):
        _emit(
            progress,
            FETCH_PROGRESS_SHARE
            + (1 - FETCH_PROGRESS_SHARE) * index / max(1, total),
            f"LLM 结构化提取 {index + 1}/{total}：{paper.title[:38]}…",
        )

        try:
            result = extractor.extract(paper.to_dict())
            save_extraction(paper.arxiv_id, result)
        except Exception as exc:
            logger.exception("提取 %s 失败", paper.arxiv_id)
            stats.extract_failed += 1
            stats.errors.append(f"{paper.arxiv_id}：{exc}")
            save_extraction_failure(paper.arxiv_id, str(exc))
            continue

        status = result.get("parse_status")
        if status == "ok":
            stats.extracted_ok += 1
        elif status == "repaired":
            stats.extracted_repaired += 1
        else:
            stats.extracted_fallback += 1

        time.sleep(LLM_SLEEP_BETWEEN_CALLS)

    stats.elapsed = time.time() - started
    _emit(progress, 1.0, stats.summary())
    return stats


# --------------------------------------------------------------------------
# CLI：便于在没有界面的情况下验证后端（也是 TDD 中「模块验证」的一环）
# --------------------------------------------------------------------------
def _main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="神经网络文献追踪看板 —— 命令行抓取与结构化"
    )
    parser.add_argument(
        "--category", "-c", action="append", choices=ALL_KEYS,
        help=f"功能方向，可重复指定。可选：{', '.join(ALL_KEYS)}",
    )
    parser.add_argument("--days", "-d", type=int, default=7, help="最近多少天（默认 7）")
    parser.add_argument("--max", "-m", type=int, default=10, help="每个方向最多抓取篇数")
    parser.add_argument("--no-llm", action="store_true", help="只抓取，不做结构化提取")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s"
    )

    keys = args.category or ALL_KEYS[:2]
    stats = run_pipeline(
        category_keys=keys,
        days=args.days,
        max_results_per_category=args.max,
        use_llm=not args.no_llm,
        progress=lambda pct, msg: print(f"[{pct * 100:5.1f}%] {msg}"),
    )
    print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2))
    return 0 if not stats.errors else 1


if __name__ == "__main__":
    sys.exit(_main())
