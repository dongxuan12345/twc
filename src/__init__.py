# -*- coding: utf-8 -*-
"""神经网络文献追踪看板 —— 后端包。

模块职责：
    config.py        全局配置（路径、密钥、限流参数）
    categories.py    神经网络「功能方向」分类表与检索式构造
    arxiv_client.py  arXiv API 抓取、Atom XML 解析、重试与限流
    llm_extractor.py 结构化 Prompt + JSON 解析 + 三级降级 + 防幻觉校验
    storage.py       SQLite 持久化与查询
    pipeline.py      抓取 → 过滤 → 入库 → 抽取 的编排
"""

__version__ = "1.0.0"
