# -*- coding: utf-8 -*-
"""翻译模块：摘要多语言翻译 + 中文检索词自动英译。

两个能力
--------
1. :meth:`Translator.translate_abstract`
   把英文摘要翻译成用户选择的语言。缓存交给 ``storage`` 层，同一篇同一语言只翻一次。

2. :func:`translate_keyword_terms`
   把中文检索词转成英文关键词，用于在英文论文库里检索。
   **优先走内置词典**（零成本、零延迟、离线可用），词典未命中才调用大模型。
   这样即使没配 API Key，"扩散模型" 这类常见词也能正常搜到英文论文。

设计原则
--------
* 翻译失败绝不阻塞页面：抛 :class:`TranslationError`，由界面捕获后提示。
* 不做"意译润色"，要求严格忠实原文，避免引入幻觉信息。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Dict, List, Optional, Tuple

from .config import DEEPSEEK_MODEL, LLM_MAX_RETRIES
from .llm_extractor import build_client

logger = logging.getLogger(__name__)


class TranslationError(RuntimeError):
    """翻译失败（未配置 Key、网络异常、空响应等）。"""


# --------------------------------------------------------------------------
# 支持的目标语言：code -> (界面显示名, 给模型看的英文名)
# --------------------------------------------------------------------------
ABSTRACT_LANGS: Dict[str, Tuple[str, str]] = {
    "zh": ("简体中文", "Simplified Chinese"),
    "en": ("English", "English"),
    "ja": ("日本語", "Japanese"),
    "ko": ("한국어", "Korean"),
    "de": ("Deutsch", "German"),
    "fr": ("Français", "French"),
    "es": ("Español", "Spanish"),
    "ru": ("Русский", "Russian"),
}


def lang_display(code: str) -> str:
    return ABSTRACT_LANGS.get(code, (code, code))[0]


def lang_for_prompt(code: str) -> str:
    return ABSTRACT_LANGS.get(code, (code, code))[1]


# --------------------------------------------------------------------------
# 中文检索词 → 英文关键词（内置词典，离线可用）
# --------------------------------------------------------------------------
# 键按长度从长到短匹配，避免「图神经网络」命中后又被「神经网络」重复命中
KEYWORD_DICT: Dict[str, str] = {
    # 模型结构
    "图神经网络": "graph neural network",
    "图卷积": "graph convolution",
    "卷积神经网络": "convolutional neural network",
    "卷积网络": "convolutional network",
    "神经网络": "neural network",
    "脉冲神经网络": "spiking neural network",
    "类脑": "neuromorphic",
    "注意力机制": "attention mechanism",
    "自注意力": "self-attention",
    "大语言模型": "large language model",
    "大模型": "large language model",
    "预训练": "pretraining",
    "微调": "fine-tuning",
    "对齐": "alignment",
    "指令微调": "instruction tuning",
    "上下文学习": "in-context learning",
    "提示学习": "prompt learning",
    "检索增强": "retrieval-augmented generation",

    # 生成与学习范式
    "扩散模型": "diffusion model",
    "扩散": "diffusion",
    "生成对抗": "generative adversarial network",
    "生成模型": "generative model",
    "变分自编码": "variational autoencoder",
    "流匹配": "flow matching",
    "强化学习": "reinforcement learning",
    "离线强化学习": "offline reinforcement learning",
    "模仿学习": "imitation learning",
    "对比学习": "contrastive learning",
    "自监督": "self-supervised",
    "无监督": "unsupervised",
    "有监督": "supervised",
    "迁移学习": "transfer learning",
    "元学习": "meta-learning",
    "持续学习": "continual learning",
    "联邦学习": "federated learning",

    # 应用方向
    "计算机视觉": "computer vision",
    "目标检测": "object detection",
    "图像分割": "image segmentation",
    "图像分类": "image classification",
    "图像生成": "image generation",
    "视频生成": "video generation",
    "多模态": "multimodal",
    "视觉语言": "vision-language",
    "视觉问答": "visual question answering",
    "语音识别": "speech recognition",
    "语音合成": "speech synthesis",
    "时间序列": "time series",
    "时序预测": "time series forecasting",
    "交通预测": "traffic prediction",
    "速度预测": "speed prediction",
    "推荐系统": "recommender system",
    "知识图谱": "knowledge graph",
    "具身智能": "embodied intelligence",
    "机器人": "robot",
    "自动驾驶": "autonomous driving",

    # 效率与工程
    "模型压缩": "model compression",
    "量化": "quantization",
    "剪枝": "pruning",
    "知识蒸馏": "knowledge distillation",
    "蒸馏": "distillation",
    "推理加速": "inference acceleration",
    "投机解码": "speculative decoding",
    "推理": "inference",
    "神经架构搜索": "neural architecture search",
    "架构搜索": "architecture search",

    # 理论与科学计算
    "物理信息": "physics-informed",
    "神经算子": "neural operator",
    "科学计算": "scientific computing",
    "泛化": "generalization",
    "优化": "optimization",
    "缩放律": "scaling law",
    "可解释": "interpretability",

    # 评测与数据
    "鲁棒性": "robustness",
    "对抗攻击": "adversarial attack",
    "对抗样本": "adversarial example",
    "基准": "benchmark",
    "数据集": "dataset",
    "零样本": "zero-shot",
    "少样本": "few-shot",

    # ---- 通用学术词：用于「自定义主题词」的逐词替换 ----
    # 有了这批词，像「电池寿命预测」这种不在领域表里的输入也能离线拼出
    # "battery lifetime prediction"，不必依赖大模型。
    "电池": "battery",
    "电池寿命": "battery lifetime",
    "寿命预测": "lifetime prediction",
    "剩余使用寿命": "remaining useful life",
    "健康状态": "state of health",
    "蛋白质": "protein",
    "分子": "molecule",
    "材料": "material",
    "晶体": "crystal",
    "气候": "climate",
    "天气": "weather",
    "遥感": "remote sensing",
    "医学影像": "medical imaging",
    "病理": "pathology",
    "药物": "drug",
    "金融": "finance",
    "股票": "stock",
    "供应链": "supply chain",
    "预测": "prediction",
    "检测": "detection",
    "分类": "classification",
    "分割": "segmentation",
    "识别": "recognition",
    "估计": "estimation",
    "生成": "generation",
    "建模": "modeling",
    "分析": "analysis",
    "学习": "learning",
    "网络": "network",
    "模型": "model",
    "算法": "algorithm",
    "方法": "method",
    "系统": "system",
    "特征": "feature",
    "训练": "training",
    "评估": "evaluation",
    "不确定性": "uncertainty",
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 中文顿号、逗号、分号、空格都视为分词边界
_SPLIT_RE = re.compile(r"[，,、;；\s]+")


def has_cjk(text: str) -> bool:
    """是否包含中文字符。"""
    return bool(_CJK_RE.search(text or ""))


def dict_lookup(text: str) -> List[str]:
    """在内置词典里查找英文关键词，返回去重后的列表。

    匹配策略：按词条长度从长到短扫描；若某个短词条是已命中长词条的子串，
    则跳过（避免「图神经网络」同时产出 graph neural network 和 neural network）。
    """
    text = (text or "").strip()
    if not text:
        return []

    matched_zh: List[str] = []
    for zh in sorted(KEYWORD_DICT, key=len, reverse=True):
        if zh in text:
            if any(zh in prev for prev in matched_zh):
                continue
            matched_zh.append(zh)

    # 若仅因为重叠而没匹配到任何词条，退一步用精确分词再试一次
    if not matched_zh:
        for token in _SPLIT_RE.split(text):
            token = token.strip()
            if token and token in KEYWORD_DICT:
                matched_zh.append(token)

    terms: List[str] = []
    for zh in matched_zh:
        en = KEYWORD_DICT[zh]
        if en not in terms:
            terms.append(en)
    return terms


# --------------------------------------------------------------------------
# 自定义主题词 → 英文检索短语
# --------------------------------------------------------------------------
def _dict_fully_covers(text: str) -> bool:
    """内置词典是否能把这段中文**完整**翻译掉（不剩任何中文字符）。"""
    rest = text
    for zh in sorted(KEYWORD_DICT, key=len, reverse=True):
        if zh in rest:
            rest = rest.replace(zh, " ")
    return not _CJK_RE.search(rest)


def dict_replace(text: str) -> str:
    """把中文按词典逐词替换成英文，剩下的中文与标点清掉。

    例：``电池寿命预测`` -> ``battery lifetime prediction``
    """
    out = text or ""
    for zh in sorted(KEYWORD_DICT, key=len, reverse=True):
        if zh in out:
            out = out.replace(zh, f" {KEYWORD_DICT[zh]} ")
    out = _CJK_RE.sub(" ", out)
    out = re.sub(r"[，,。、；;：:（）()【】\[\]\"'“”]", " ", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def translate_topic(text: str) -> Tuple[str, str]:
    """把用户自填的主题词翻成英文检索短语。

    Returns:
        ``(english_term, source)``，source ∈ {empty, ascii, dict, llm, failed}

    策略：**能离线拼出来就绝不花钱**——词典能完整覆盖时走 dict；
    覆盖不全才调用大模型；都不行则返回空串，由界面提示用户。
    """
    text = (text or "").strip()
    if not text:
        return "", "empty"
    if not has_cjk(text):
        return text, "ascii"

    if _dict_fully_covers(text):
        phrase = dict_replace(text)
        if phrase:
            return phrase, "dict"

    try:
        translator = Translator()
        if translator.available:
            raw = translator.translate_keyword(text)
            phrase = re.split(r"[,，;；]", raw)[0].strip()
            if phrase:
                return phrase, "llm"
    except Exception as exc:
        logger.warning("主题词翻译失败：%s", exc)

    return "", "failed"


# --------------------------------------------------------------------------
# 翻译器
# --------------------------------------------------------------------------
ABSTRACT_PROMPT = """你是专业的学术翻译。请把下面这段英文论文摘要翻译成{lang}。

要求：
1. 只输出译文本身，不要任何解释、前缀、标题，也不要用 ``` 包裹。
2. 保持学术语体，句子通顺；允许调整语序，但不得增删信息。
3. 数据集名、模型名、指标名（如 ImageNet、LLaMA-3、FID、MAE）保留英文原文。
4. 不要添加原文没有的任何内容。

【英文摘要】
{text}"""

KEYWORD_PROMPT = """把下面的中文科研检索词翻译成英文的关键词，用于在 arXiv 英文论文库中检索。

要求：
1. 只输出英文关键词，不要解释、不要引号、不要句号。
2. 若包含多个概念，用英文逗号分隔，最多 3 个。
3. 优先使用该领域通用的英文术语。

【中文检索词】{text}"""


class Translator:
    """基于 LLM 的翻译器。未配置 Key 时 ``available`` 为 False。"""

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or DEEPSEEK_MODEL
        self._client = build_client()

    @property
    def available(self) -> bool:
        return self._client is not None

    # ---------------- 对外方法 ----------------
    def translate_abstract(self, text: str, target_lang: str) -> str:
        """把英文摘要翻译成 ``target_lang``。目标语言是英文时直接返回原文。"""
        text = (text or "").strip()
        if not text:
            raise TranslationError("摘要为空，无法翻译")
        if target_lang == "en":
            return text
        if not self.available:
            raise TranslationError("未配置 DEEPSEEK_API_KEY，无法调用翻译服务")

        prompt = ABSTRACT_PROMPT.format(
            lang=lang_for_prompt(target_lang), text=text[:4000]
        )
        return self._chat(prompt).strip()

    def translate_keyword(self, text: str) -> str:
        """把中文检索词翻译成英文关键词字符串（多个用逗号分隔）。"""
        text = (text or "").strip()
        if not text:
            return ""
        if not self.available:
            raise TranslationError("未配置 DEEPSEEK_API_KEY，无法翻译检索词")

        raw = self._chat(KEYWORD_PROMPT.format(text=text)).strip()
        # 清理模型偶尔带出来的引号、句号、换行
        raw = raw.replace("\n", " ").strip(" \"'“”。.；;")
        return re.sub(r"\s{2,}", " ", raw)

    # ---------------- 内部 ----------------
    def _chat(self, prompt: str) -> str:
        if not self.available:
            raise TranslationError("未配置 DEEPSEEK_API_KEY")

        last_error: Optional[Exception] = None
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,   # 翻译要忠实，但允许轻微语序调整
                )
                content = (resp.choices[0].message.content or "").strip()
                if not content:
                    raise TranslationError("模型返回空译文")
                return content
            except TranslationError:
                raise
            except Exception as exc:
                last_error = exc
                sleep_s = min(2 ** attempt, 8)
                logger.warning(
                    "翻译调用异常（第 %d/%d 次）：%s，%.1f 秒后重试",
                    attempt, LLM_MAX_RETRIES, str(exc)[:200], sleep_s,
                )
                time.sleep(sleep_s)

        raise TranslationError(f"连续 {LLM_MAX_RETRIES} 次翻译调用失败：{last_error}")


# --------------------------------------------------------------------------
# 检索词翻译入口（供界面直接调用）
# --------------------------------------------------------------------------
def translate_keyword_terms(text: str) -> Tuple[List[str], str]:
    """把检索词转成英文关键词列表。

    Returns:
        ``(terms, source)``，其中 ``source`` 取值：

        * ``"empty"``  输入为空
        * ``"ascii"``  输入已经是英文，无需翻译
        * ``"dict"``   命中内置词典（零成本）
        * ``"llm"``    调用大模型翻译成功
        * ``"failed"`` 词典未命中且模型不可用/调用失败
    """
    text = (text or "").strip()
    if not text:
        return [], "empty"
    if not has_cjk(text):
        return [], "ascii"

    terms = dict_lookup(text)
    if terms:
        return terms, "dict"

    try:
        translator = Translator()
        if not translator.available:
            return [], "failed"
        raw = translator.translate_keyword(text)
    except Exception as exc:
        logger.warning("检索词翻译失败：%s", exc)
        return [], "failed"

    parsed = [
        part.strip()
        for part in re.split(r"[,，;；]", raw)
        if part.strip()
    ]
    return parsed[:3], ("llm" if parsed else "failed")


if __name__ == "__main__":  # 手工冒烟：python -m src.translator
    logging.basicConfig(level=logging.INFO)
    for sample in ["扩散模型", "图神经网络的推理加速", "transformer"]:
        print(sample, "->", translate_keyword_terms(sample))
