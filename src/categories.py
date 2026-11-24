# -*- coding: utf-8 -*-
"""神经网络「功能方向」分类表。

为什么按功能分类而不是直接用 cs.LG / cs.AI 大杂烩检索？
--------------------------------------------------------
`cs.LG` 每天新增数百篇，直接按类目抓回来，看板会被与你的关注点无关的
论文淹没，"关键词搜索"和"按开源筛选"也就失去意义。本作业的核心诉求是
「面向特定细分领域」，因此这里把神经网络按**功能**切成 13 个方向，
每个方向 = 一个可独立追踪的细分领域。

一个方向包含两部分：
1. ``arxiv_cat``  —— 用于 arXiv API 服务端过滤的主类目（保证召回）；
2. ``keywords``   —— 用于客户端二次过滤的领域词（保证精度）。

采用「服务端宽召回 + 客户端精筛」的两阶段策略，原因是 arXiv 的
``abs:"phrase"`` 组合检索对短语要求过严，直接放进 search_query 常常
返回 0 条；而先按类目拿到候选、再在本地过滤，既有数据可展示，又能
保证落库的论文确实属于该方向（详见 技术设计文档.md 第 3.2 节）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Category:
    """一个神经网络功能方向的检索配方。"""

    key: str                      # 稳定英文标识，入库用，不要随意改
    name: str                     # 中文展示名
    arxiv_cat: str                # arXiv 主类目
    keywords: Tuple[str, ...] = field(default_factory=tuple)  # 客户端过滤词（小写）
    desc: str = ""                # 一句话说明：这个方向研究什么

    def query_terms(self) -> List[str]:
        return list(self.keywords)


CATEGORIES: List[Category] = [
    Category(
        key="cnn_vision",
        name="卷积神经网络 / 计算机视觉",
        arxiv_cat="cs.CV",
        keywords=(
            "convolutional neural network", "convnet", "cnn",
            "vision transformer", "image classification",
            "object detection", "semantic segmentation", "backbone",
        ),
        desc="图像分类、检测、分割等视觉任务的骨干网络与卷积结构改进",
    ),
    Category(
        key="transformer_llm",
        name="Transformer / 大语言模型",
        arxiv_cat="cs.CL",
        keywords=(
            "transformer", "large language model", "llm", "attention mechanism",
            "in-context learning", "prompt", "instruction tuning",
        ),
        desc="注意力机制、预训练语言模型、上下文学习与对齐方法",
    ),
    Category(
        key="gnn",
        name="图神经网络 (GNN)",
        arxiv_cat="cs.LG",
        keywords=(
            "graph neural network", "gnn", "message passing",
            "graph representation learning", "graph transformer",
        ),
        desc="图结构数据上的消息传递网络、分子/社交/知识图谱建模",
    ),
    Category(
        key="generative",
        name="生成模型（扩散 / GAN / VAE）",
        arxiv_cat="cs.LG",
        keywords=(
            "diffusion model", "generative adversarial", "variational autoencoder",
            "flow matching", "score-based", "image generation", "normalizing flow",
        ),
        desc="扩散模型、对抗生成网络、变分自编码器等生成式建模范式",
    ),
    Category(
        key="rl",
        name="强化学习与决策",
        arxiv_cat="cs.LG",
        keywords=(
            "reinforcement learning", "policy gradient", "actor-critic",
            "q-learning", "world model", "offline rl", "reward model",
        ),
        desc="策略优化、离线强化学习、世界模型与智能体决策",
    ),
    Category(
        key="pinn",
        name="物理信息神经网络 (PINN)",
        arxiv_cat="cs.LG",
        keywords=(
            "physics-informed", "pinn", "neural operator", "pde",
            "scientific machine learning", "physics-informed neural",
        ),
        desc="把物理方程作为约束嵌入损失函数的科学计算神经网络",
    ),
    Category(
        key="theory_optim",
        name="神经网络理论与优化",
        arxiv_cat="cs.LG",
        keywords=(
            "generalization bound", "optimization", "scaling law",
            "training dynamics", "expressivity", "implicit bias", "loss landscape",
        ),
        desc="泛化理论、优化动力学、缩放律与表示能力分析",
    ),
    Category(
        key="timeseries",
        name="时间序列与序列建模",
        arxiv_cat="cs.LG",
        keywords=(
            "time series", "forecasting", "temporal modeling",
            "state space model", "sequence modeling", "traffic prediction",
        ),
        desc="时序预测、状态空间模型与长序列建模（含车辆速度预测等）",
    ),
    Category(
        key="multimodal",
        name="多模态 / 视觉-语言",
        arxiv_cat="cs.CV",
        keywords=(
            "multimodal", "vision-language", "vlm", "image-text",
            "cross-modal", "clip", "visual question answering",
        ),
        desc="图文对齐、视觉问答、跨模态表征与统一大模型",
    ),
    Category(
        key="efficient",
        name="高效推理与模型压缩",
        arxiv_cat="cs.LG",
        keywords=(
            "quantization", "pruning", "knowledge distillation",
            "efficient inference", "speculative decoding", "kv cache",
            "inference acceleration",
        ),
        desc="量化、剪枝、蒸馏、投机解码等推理加速与部署优化",
    ),
    Category(
        key="nas",
        name="神经架构搜索 (NAS)",
        arxiv_cat="cs.LG",
        keywords=(
            "neural architecture search", "nas", "architecture search",
            "differentiable architecture", "auto-design",
        ),
        desc="自动化搜索网络结构与超参数，替代人工设计",
    ),
    Category(
        key="snn",
        name="脉冲神经网络 / 类脑计算",
        arxiv_cat="cs.NE",
        keywords=(
            "spiking neural network", "snn", "neuromorphic",
            "spike-timing", "event-driven", "brain-inspired",
        ),
        desc="事件驱动、低功耗的脉冲网络与神经形态硬件协同设计",
    ),
    Category(
        key="speech",
        name="语音与音频神经网络",
        arxiv_cat="eess.AS",
        keywords=(
            "speech recognition", "speech synthesis", "asr", "text-to-speech",
            "neural codec", "audio generation", "speech enhancement",
        ),
        desc="语音识别、语音合成、音频生成与神经编解码",
    ),
]

CATEGORY_MAP: Dict[str, Category] = {c.key: c for c in CATEGORIES}
ALL_KEYS: List[str] = [c.key for c in CATEGORIES]


def get_category(key: str) -> Category:
    """按 key 取方向，key 非法时抛出清晰的错误而不是 KeyError。"""
    try:
        return CATEGORY_MAP[key]
    except KeyError as exc:  # pragma: no cover - 防御式分支
        raise KeyError(
            f"未知的神经网络功能方向: {key!r}；可用取值: {', '.join(ALL_KEYS)}"
        ) from exc


def display_name(key: str) -> str:
    """给界面用的展示名，找不到时原样返回。"""
    cat = CATEGORY_MAP.get(key)
    return cat.name if cat else key


# Streamlit 多选框需要的 options / format_func 映射
NAME_BY_KEY: Dict[str, str] = {c.key: c.name for c in CATEGORIES}
DESC_BY_KEY: Dict[str, str] = {c.key: c.desc for c in CATEGORIES}
