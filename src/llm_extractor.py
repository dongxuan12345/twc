# -*- coding: utf-8 -*-
"""LLM 结构化提取模块（本作业「AI 结构化提取」与「防幻觉」的核心）。

四层防线
--------
1. **Prompt 约束**：system prompt + 3 组 Few-shot 示例，明确要求「只输出 JSON」；
   同时开启 ``response_format={"type": "json_object"}`` 让接口层面也约束格式。
2. **容错解析**：模型仍可能返回 ```json 包裹、前后带解释文字、尾逗号等情况，
   :func:`parse_structured_output` 用「代码块剥离 → 括号配对 → JSON 修复」三级解析。
3. **失败重试**：解析失败时，把非法输出回灌给模型并追加修复指令，让它自己纠正一次。
4. **降级不崩**：两次都失败则返回 ``parse_status="fallback"``，保留原始响应与
   英文摘要，看板显示「结构化提取失败（已保留原文）」，绝不抛异常打断整批任务。

另有**防幻觉**后处理：模型给出的 code_url 必须能在摘要原文中找到对应字样，
否则视为幻觉并丢弃；模型说开源但给不出链接，则降级为 ``unknown``。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT,
    PLACEHOLDER_KEYS,
)

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """调用大模型失败（网络、鉴权、空响应等）。"""


class JSONParseError(ValueError):
    """模型输出无法解析为 JSON。"""


# --------------------------------------------------------------------------
# 1. Prompt
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """你是一名严谨的科研文献信息抽取助手，服务于「神经网络领域文献追踪看板」。

你的唯一任务：阅读一篇神经网络相关论文的英文摘要，把它抽取为固定的 JSON 结构。

## 硬性规则
1. 只输出一个 JSON 对象。不要输出任何解释、前言、后记，不要用 ```json 包裹。
2. 所有取值必须来自给定摘要原文，禁止用你的先验知识补充摘要里没写的信息。
3. 摘要没有提到的字段填 null（或空数组 []），绝不能猜测。
4. one_line_contribution 用中文，不超过 60 个汉字，聚焦「解决了什么问题 + 用了什么关键做法」。
5. datasets_methods 抽取具体的「数据集名 / 模型名 / 方法名」，2~5 个；
   不要写 "deep learning"、"neural network" 这类泛词。
6. code_open_source 只能是 "yes" / "no" / "unknown" 三者之一：
   - 摘要里给出代码仓库链接（github / gitlab / huggingface 等）→ "yes"
   - 摘要明确声明不开源、代码暂不公开 → "no"
   - 摘要完全没提代码 → "unknown"（不要因为「论文通常都开源」就写 yes）
7. code_url 只在摘要中出现真实链接时填写，否则 null。
8. evidence 必须逐字摘自摘要原文的一句英文，用来支撑你的 one_line_contribution。

## 输出结构
{"one_line_contribution": "中文一句话结论",
 "datasets_methods": ["数据集或方法名", "..."],
 "code_open_source": "yes | no | unknown",
 "code_url": "https://... 或 null",
 "evidence": "支撑上述结论的英文原文片段"}
"""

USER_TEMPLATE = """请抽取下面这篇论文。

【标题】{title}
【arXiv 主类目】{category}
【作者备注】{comment}
【英文摘要】
{abstract}

现在只输出那个 JSON 对象。"""

REPAIR_PROMPT = (
    "你上一条回复不是合法的 JSON 对象，程序无法解析。\n"
    "请重新只输出一个 JSON 对象，严格符合下面的结构，"
    "不要任何解释文字，也不要用 ``` 包裹：\n"
    '{"one_line_contribution": "中文一句话", "datasets_methods": ["..."], '
    '"code_open_source": "yes|no|unknown", "code_url": null, "evidence": "英文原文片段"}'
)

# 3 组 Few-shot：分别覆盖「有代码链接」「未提代码」「明确不开源」三种典型情况，
# 让模型看到 code_open_source 三态的判定边界。
FEW_SHOT: List[Dict[str, Dict[str, Any]]] = [
    {
        "input": {
            "title": "GraphMixer: A Message-Passing Network for Molecular Property Prediction",
            "category": "cs.LG",
            "comment": "9 pages, 4 figures",
            "abstract": (
                "We present GraphMixer, a message-passing network for molecular property "
                "prediction. On QM9 and ZINC, GraphMixer improves MAE by 12% over GNN "
                "baselines. Code is available at https://github.com/example/graphmixer."
            ),
        },
        "output": {
            "one_line_contribution": "提出 GraphMixer 消息传递网络，在 QM9 与 ZINC 上比 GNN 基线降低 12% MAE",
            "datasets_methods": ["QM9", "ZINC", "GraphMixer", "message passing"],
            "code_open_source": "yes",
            "code_url": "https://github.com/example/graphmixer",
            "evidence": "On QM9 and ZINC, GraphMixer improves MAE by 12% over GNN baselines.",
        },
    },
    {
        "input": {
            "title": "Fast Sampling for Diffusion Models via Distillation",
            "category": "cs.LG",
            "comment": "",
            "abstract": (
                "Diffusion models achieve strong image generation quality but sampling is "
                "slow. We propose a distilled sampler that reduces steps from 1000 to 4 "
                "while preserving FID on CIFAR-10 and ImageNet 64x64."
            ),
        },
        "output": {
            "one_line_contribution": "提出蒸馏采样器，把扩散模型采样步数从 1000 降到 4 且保持 CIFAR-10 上的 FID",
            "datasets_methods": ["CIFAR-10", "ImageNet 64x64", "distilled sampler"],
            "code_open_source": "unknown",
            "code_url": None,
            "evidence": "We propose a distilled sampler that reduces steps from 1000 to 4 while preserving FID on CIFAR-10 and ImageNet 64x64.",
        },
    },
    {
        "input": {
            "title": "Physics-Informed Neural Operators for Subsurface Flow",
            "category": "cs.LG",
            "comment": "",
            "abstract": (
                "We introduce a physics-informed neural operator for subsurface flow. "
                "The dataset is proprietary and the code will not be released."
            ),
        },
        "output": {
            "one_line_contribution": "提出面向地下水流建模的物理信息神经算子",
            "datasets_methods": ["physics-informed neural operator", "subsurface flow"],
            "code_open_source": "no",
            "code_url": None,
            "evidence": "The dataset is proprietary and the code will not be released.",
        },
    },
]

# 摘要超长时截断，控制单次 token 成本（arXiv 摘要一般在 1500 字符内）
MAX_ABSTRACT_CHARS = 4000


# --------------------------------------------------------------------------
# 2. 容错 JSON 解析
# --------------------------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json|JSON)?", re.IGNORECASE)


def _strip_code_fence(text: str) -> str:
    return _FENCE_RE.sub("", text).replace("```", "").strip()


def _find_balanced_object(text: str) -> Optional[str]:
    """从任意文本中找出第一个完整、括号配对且考虑字符串转义的 JSON 对象。

    比 ``text[text.find('{'): text.rfind('}')+1]`` 更稳：能正确跳过
    字符串内部的 ``{`` ``}``，也能在模型输出了多段 JSON 时只取第一段。
    """
    for start, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            cur = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif cur == "\\":
                    escaped = True
                elif cur == '"':
                    in_string = False
                continue
            if cur == '"':
                in_string = True
            elif cur == "{":
                depth += 1
            elif cur == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _repair_common_issues(candidate: str) -> str:
    """修掉模型最常犯的 JSON 语法错误：尾逗号、中文引号。"""
    fixed = candidate.replace("“", '"').replace("”", '"')
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)   # {"a":1,} -> {"a":1}
    return fixed


def parse_structured_output(text: str) -> Dict[str, Any]:
    """把模型返回的文本解析成 dict，失败抛 :class:`JSONParseError`。"""
    if not text or not text.strip():
        raise JSONParseError("模型返回空内容")

    cleaned = _strip_code_fence(text)

    candidates: List[str] = []
    if cleaned.startswith("{"):
        candidates.append(cleaned)
    balanced = _find_balanced_object(cleaned)
    if balanced and balanced not in candidates:
        candidates.append(balanced)
    candidates.append(cleaned)  # 最后再原样试一次

    last_error: Optional[Exception] = None
    for candidate in candidates:
        for text_variant in (candidate, _repair_common_issues(candidate)):
            try:
                data = json.loads(text_variant)
            except (json.JSONDecodeError, TypeError) as exc:
                last_error = exc
                continue
            if isinstance(data, dict):
                return data
            last_error = JSONParseError(f"顶层不是 JSON 对象，而是 {type(data).__name__}")

    snippet = (cleaned or "")[:160].replace("\n", " ")
    raise JSONParseError(f"无法解析为 JSON：{last_error}；模型原文开头：{snippet}")


# --------------------------------------------------------------------------
# 3. 字段归一化与防幻觉校验
# --------------------------------------------------------------------------
CODE_URL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(?:github\.com|gitlab\.com|huggingface\.co|bitbucket\.org|codeocean\.com|zenodo\.org)"
    r"/[^\s\)\]\},;\"'<>]+",
    re.IGNORECASE,
)

_OPEN_SOURCE_MAP = {
    "yes": "yes", "y": "yes", "true": "yes", "是": "yes", "有": "yes",
    "open": "yes", "open-source": "yes", "opensource": "yes", "available": "yes",
    "no": "no", "n": "no", "false": "no", "否": "no", "没有": "no",
    "closed": "no", "not available": "no", "unavailable": "no",
    "unknown": "unknown", "未知": "unknown", "unclear": "unknown",
    "none": "unknown", "null": "unknown", "n/a": "unknown",
}

BANNED_GENERIC_TERMS = {
    "deep learning", "neural network", "neural networks", "machine learning",
    "artificial intelligence", "ai", "model", "method", "dataset", "data",
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "；".join(str(v) for v in value if v is not None)
    return str(value).strip()


def _normalize_datasets(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,;，、/]", value)
    elif isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        return []

    result: List[str] = []
    seen = set()
    for part in parts:
        item = str(part).strip().strip("-•*").strip()
        if not item or len(item) > 60:
            continue
        if item.lower() in BANNED_GENERIC_TERMS:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 6:
            break
    return result


def _normalize_open_source(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = _as_text(value).lower().strip().strip("。.!！,，;；")
    if not text:
        return "unknown"
    if text in _OPEN_SOURCE_MAP:
        return _OPEN_SOURCE_MAP[text]
    # 只对长度 >= 4 的键做子串匹配：像 "y" / "no" 这种短键做子串匹配会误伤
    # （例如 "not yet released" 里含字母 y，却绝不该判成 yes）
    for key, mapped in _OPEN_SOURCE_MAP.items():
        if len(key) >= 4 and key in text:
            return mapped
    return "unknown"


def _normalize_url(value: Any) -> Optional[str]:
    """从字段值中提取第一个合法的代码仓库链接。"""
    if value is None:
        return None
    text = _as_text(value)
    if not text:
        return None
    match = CODE_URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:)]}'\"’")


def _normalize_source_text(text: str) -> str:
    """把 URL 与原文都规范成「去掉协议/www/首尾斜杠的小写串」，便于比对。"""
    return (
        (text or "")
        .lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
    )


def _url_supported_by_source(url: str, source_text: str) -> bool:
    """防幻觉：模型给的仓库链接必须能在摘要/备注原文里找到（允许格式差异）。"""
    normalized_url = _normalize_source_text(url).rstrip("/")
    # 只比对 host+path，避免协议、末尾斜杠差异导致误判
    return normalized_url in _normalize_source_text(source_text)


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _valid_key(key: Optional[str]) -> bool:
    """Key 是否「看起来」可用：非空、不是占位符、长度合理。"""
    key = (key or "").strip()
    if len(key) < 8:
        return False
    return key.lower() not in PLACEHOLDER_KEYS


def build_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
):
    """构造 OpenAI 兼容客户端；不可用时返回 None（而不是抛异常）。

    抽出成模块级函数，是因为「结构化提取」和「摘要翻译」两个功能
    需要完全相同的客户端配置，重复实现容易导致配置漂移。
    """
    key = api_key or DEEPSEEK_API_KEY
    if not _valid_key(key):
        logger.warning("未配置有效的 DEEPSEEK_API_KEY，LLM 功能不可用")
        return None

    try:
        from openai import OpenAI  # 延迟导入，未安装时不影响抓取功能
    except ImportError:
        logger.error("未安装 openai 库，请执行 pip install -r requirements.txt")
        return None

    try:
        return OpenAI(
            api_key=key,
            base_url=base_url or DEEPSEEK_BASE_URL,
            timeout=timeout or LLM_TIMEOUT,
            max_retries=0,   # 重试由调用方控制，便于按错误类型分别处理
        )
    except Exception as exc:  # pragma: no cover
        logger.error("初始化 LLM 客户端失败：%s", exc)
        return None


# --------------------------------------------------------------------------
# 4. 提取器
# --------------------------------------------------------------------------
class LLMExtractor:
    """把一篇论文的英文摘要转成结构化字段。

    用法::

        extractor = LLMExtractor()
        if extractor.available:
            result = extractor.extract(paper_dict)
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.model = model or DEEPSEEK_MODEL
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url or DEEPSEEK_BASE_URL
        self._json_mode = True   # 若不支持 response_format 会自动降级
        self._client = self._build_client()

    # ---------------- 初始化 ----------------
    def _build_client(self):
        return build_client(self.api_key, self.base_url)

    @property
    def available(self) -> bool:
        return self._client is not None

    # ---------------- 对外入口 ----------------
    def extract(self, paper: Dict[str, Any]) -> Dict[str, Any]:
        """提取单篇论文。永不抛异常：失败时返回带 ``parse_status`` 的降级结果。"""
        if not self.available:
            raise LLMError("LLM 未配置：请在 .env 中设置 DEEPSEEK_API_KEY")

        messages = self._build_messages(paper)

        try:
            raw = self._chat(messages)
        except LLMError as exc:
            logger.error("[%s] LLM 调用失败：%s", paper.get("arxiv_id"), exc)
            return self._fallback(paper, "", f"LLM 调用失败：{exc}")

        status = "ok"
        data: Optional[Dict[str, Any]] = None

        try:
            data = parse_structured_output(raw)
        except JSONParseError as exc:
            logger.warning(
                "[%s] 首次 JSON 解析失败，触发修复重试：%s", paper.get("arxiv_id"), exc
            )
            # 第 2 次：把非法输出回灌 + 修复指令
            repair_messages = messages + [
                {"role": "assistant", "content": _clip(raw, 1500)},
                {"role": "user", "content": REPAIR_PROMPT},
            ]
            try:
                raw_retry = self._chat(repair_messages)
                data = parse_structured_output(raw_retry)
                raw, status = raw_retry, "repaired"
            except (JSONParseError, LLMError) as retry_exc:
                logger.error(
                    "[%s] 修复重试仍失败，降级为原始摘要展示：%s",
                    paper.get("arxiv_id"), retry_exc,
                )
                return self._fallback(paper, raw, f"JSON 解析失败：{retry_exc}")

        return self._post_process(paper, data or {}, raw, status)

    # ---------------- 内部 ----------------
    def _build_messages(self, paper: Dict[str, Any]) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        for example in FEW_SHOT:
            messages.append(
                {"role": "user", "content": USER_TEMPLATE.format(**example["input"])}
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(example["output"], ensure_ascii=False),
                }
            )

        abstract = _clip(paper.get("abstract") or "", MAX_ABSTRACT_CHARS)
        messages.append(
            {
                "role": "user",
                "content": USER_TEMPLATE.format(
                    title=paper.get("title", ""),
                    category=paper.get("primary_category", ""),
                    comment=paper.get("comment", "") or "（无）",
                    abstract=abstract,
                ),
            }
        )
        return messages

    def _chat(self, messages: List[Dict[str, str]]) -> str:
        """带重试与 json 模式自动降级的对话调用。"""
        last_error: Optional[Exception] = None

        for attempt in range(1, LLM_MAX_RETRIES + 1):
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 0,       # 结构化抽取要的是稳定，不是创意
                "timeout": LLM_TIMEOUT,
            }
            if self._json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            try:
                resp = self._client.chat.completions.create(**kwargs)
                content = (resp.choices[0].message.content or "").strip()
                if not content:
                    raise LLMError("模型返回空内容")
                return content

            except Exception as exc:  # openai 的异常类型随版本变化，统一兜住
                message = str(exc)
                lowered = message.lower()

                # 某些兼容服务不支持 json_object，关掉后立即重试一次
                if self._json_mode and (
                    "response_format" in lowered or "json_object" in lowered
                ):
                    logger.warning("当前端点不支持 json_object，已退回纯文本约束模式")
                    self._json_mode = False
                    continue

                last_error = exc
                sleep_s = min(2 ** attempt, 8)
                logger.warning(
                    "LLM 调用异常（第 %d/%d 次）：%s，%.1f 秒后重试",
                    attempt, LLM_MAX_RETRIES, message[:200], sleep_s,
                )
                time.sleep(sleep_s)

        raise LLMError(f"连续 {LLM_MAX_RETRIES} 次调用失败：{last_error}")

    def _post_process(
        self,
        paper: Dict[str, Any],
        data: Dict[str, Any],
        raw: str,
        status: str,
    ) -> Dict[str, Any]:
        contribution = _clip(_as_text(data.get("one_line_contribution")), 220)
        datasets = _normalize_datasets(data.get("datasets_methods"))
        open_source = _normalize_open_source(data.get("code_open_source"))
        evidence = _clip(_as_text(data.get("evidence")), 400)

        source_text = f"{paper.get('abstract', '')} {paper.get('comment', '')}"

        # --- 防幻觉 1：模型给的链接必须在原文里出现过 ---
        llm_url = _normalize_url(data.get("code_url"))
        if llm_url and not _url_supported_by_source(llm_url, source_text):
            logger.warning(
                "[%s] 丢弃疑似幻觉链接 %s（摘要中未出现）", paper.get("arxiv_id"), llm_url
            )
            llm_url = None

        # --- 防幻觉 2：链接以原文正则为准，模型说了不算 ---
        regex_url = _normalize_url(source_text)
        code_url = llm_url or regex_url

        # --- 三态一致性修正 ---
        if open_source == "yes" and not code_url:
            # 说开源却拿不出链接 -> 证据不足，降级为未知而不是硬编 yes
            open_source = "unknown"
        elif code_url and open_source != "no":
            open_source = "yes"
        elif code_url and open_source == "no":
            # 原文明明有链接却判 no，以证据为准
            open_source = "yes"

        # 一句话贡献为空视为抽取失败
        if not contribution:
            return self._fallback(paper, raw, "模型未给出 one_line_contribution")

        return {
            "one_line_contribution": contribution,
            "datasets_methods": datasets,
            "code_open_source": open_source,
            "code_url": code_url,
            "evidence": evidence,
            "model": self.model,
            "parse_status": status,
            "raw_response": _clip(raw, 4000),
        }

    def _fallback(
        self, paper: Dict[str, Any], raw: str, reason: str
    ) -> Dict[str, Any]:
        """统一的降级结果：字段留空，但保证论文本身仍可展示。"""
        logger.info("[%s] 使用降级结果：%s", paper.get("arxiv_id"), reason)
        return {
            "one_line_contribution": None,
            "datasets_methods": [],
            "code_open_source": "unknown",
            "code_url": _normalize_url(
                f"{paper.get('abstract', '')} {paper.get('comment', '')}"
            ),
            "evidence": None,
            "model": self.model,
            "parse_status": "fallback",
            "raw_response": _clip(f"{reason}\n\n---\n{raw}", 4000),
        }


# --------------------------------------------------------------------------
# 便捷函数（供 CLI / 单测使用）
# --------------------------------------------------------------------------
def extract_one(paper: Dict[str, Any]) -> Dict[str, Any]:
    return LLMExtractor().extract(paper)


if __name__ == "__main__":  # 手工冒烟测试：python -m src.llm_extractor
    logging.basicConfig(level=logging.INFO)
    demo = {
        "arxiv_id": "demo.0001",
        "title": "A Simple Demo",
        "primary_category": "cs.LG",
        "comment": "",
        "abstract": (
            "We propose DemoNet for time series forecasting. Experiments on ETTh1 "
            "and Weather show 8% MSE reduction. Code: https://github.com/demo/demonet"
        ),
    }
    _extractor = LLMExtractor()
    if not _extractor.available:
        print("未配置 DEEPSEEK_API_KEY，跳过在线冒烟测试（离线逻辑请跑 tests/smoke_test.py）")
        raise SystemExit(0)
    print(json.dumps(_extractor.extract(demo), ensure_ascii=False, indent=2))
