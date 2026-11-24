# -*- coding: utf-8 -*-
"""全局配置：路径、密钥、限流参数。

设计原则
--------
1. 所有可调参数集中在此，其他模块只 import，不在别处重复定义常量。
2. 密钥一律从环境变量 /.env 读取，仓库代码里只允许出现占位符 "Your Key"。
3. 每个参数都有安全的默认值，缺少 .env 时程序仍能启动（LLM 功能降级关闭）。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

# override=False：已经存在的系统环境变量优先级高于 .env 文件
load_dotenv(ENV_FILE, override=False)

DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "papers.db"


def ensure_dirs() -> None:
    """创建运行时需要的目录（幂等）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# 大模型（LLM）
# --------------------------------------------------------------------------
# 这些值会被认为是「未配置」，用于避免把占位符当成真 Key 发请求
PLACEHOLDER_KEYS = {
    "",
    "your key",
    "your_key",
    "yourkey",
    "sk-xxx",
    "sk-your-key",
    "none",
    "null",
    "changeme",
    "replace_me",
}

def _read_setting(name: str, default: str = "") -> str:
    """读取配置：环境变量 → Streamlit secrets → 默认值。

    为什么要走两条路：
    * 本地跑 `streamlit run app.py` 时，.env 由 python-dotenv 载入环境变量；
    * 部署到 Streamlit Community Cloud 时，密钥放在平台的 Secrets 里，
      只能通过 ``st.secrets`` 读到，环境变量里是空的。
    """
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st  # 延迟导入：CLI 环境不需要 Streamlit
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        # 没有 streamlit、没有 secrets.toml、或不在 Streamlit 运行时里，都属正常
        pass
    return default


DEEPSEEK_API_KEY = _read_setting("DEEPSEEK_API_KEY", "Your Key")
DEEPSEEK_BASE_URL = _read_setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _read_setting("DEEPSEEK_MODEL", "deepseek-chat")

LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_SLEEP_BETWEEN_CALLS = float(os.getenv("LLM_SLEEP_BETWEEN_CALLS", "0.5"))


def is_llm_configured() -> bool:
    """判断是否配置了可用的 LLM Key（占位符不算）。"""
    key = (DEEPSEEK_API_KEY or "").strip()
    if not key:
        return False
    if key.lower() in PLACEHOLDER_KEYS:
        return False
    return len(key) >= 8


def masked_key() -> str:
    """返回脱敏后的 Key，用于界面展示与日志，避免密钥泄露。"""
    key = (DEEPSEEK_API_KEY or "").strip()
    if not key or key.lower() in PLACEHOLDER_KEYS:
        return "未配置"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 8}{key[-4:]}"


# --------------------------------------------------------------------------
# arXiv API
# --------------------------------------------------------------------------
ARXIV_API_URL = os.getenv("ARXIV_API_URL", "https://export.arxiv.org/api/query")
ARXIV_MIN_INTERVAL = float(os.getenv("ARXIV_MIN_INTERVAL", "3.0"))
ARXIV_MAX_RETRIES = int(os.getenv("ARXIV_MAX_RETRIES", "3"))
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
ARXIV_PAGE_SIZE = int(os.getenv("ARXIV_PAGE_SIZE", "100"))

# 单次抓取的硬上限，防止误操作把 arXiv 打爆
MAX_RESULTS_HARD_CAP = 300

# --------------------------------------------------------------------------
# 业务默认值
# --------------------------------------------------------------------------
DEFAULT_DAYS = 7
DEFAULT_YEARS = 0.5          # 界面默认时间窗口：半年（0.5 年 ≈ 183 天）
DEFAULT_MAX_RESULTS = 30
DEFAULT_FETCH_LIMIT = 120  # 看板默认最多渲染多少条
