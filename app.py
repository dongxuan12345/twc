# -*- coding: utf-8 -*-
"""神经网络领域文献追踪看板 —— Streamlit 前端入口。

运行：
    streamlit run app.py

v1.2 变更
---------
1. **语言切换改成显式按钮组**（中文 | English），不再是藏在角落的下拉框。
2. **主题**：跟随系统 / 白天 / 黑夜 三态。跟随系统用 CSS 的
   ``prefers-color-scheme`` 媒体查询实现，不需要 JS。
3. **自定义主题词**：不再局限于 13 个预置方向，任何主题都能录入，
   中文自动翻成英文检索词（先查词典，覆盖不全才调模型）。
4. **显式搜索按钮**：关键词放进 ``st.form``，只有点「🔍 搜索」才生效，
   避免边打字边发请求。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

# 保证「从仓库根目录 streamlit run app.py」时能 import src 包
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.categories import ALL_KEYS, DESC_BY_KEY, NAME_BY_KEY
from src.config import (
    DEFAULT_FETCH_LIMIT,
    DEFAULT_MAX_RESULTS,
    DEFAULT_YEARS,
    DEEPSEEK_MODEL,
    is_llm_configured,
    masked_key,
)
from src.i18n import DEFAULT_UI_LANG, UI_LANGS, status_hint, t
from src.pipeline import run_pipeline
from src.storage import (
    category_counts,
    clear_all,
    get_fetch_log,
    get_keyword_cache,
    get_overview,
    get_translation,
    init_db,
    query_papers,
    save_keyword_cache,
    save_translation,
)
from src.translator import (
    ABSTRACT_LANGS,
    Translator,
    has_cjk,
    lang_display,
    translate_keyword_terms,
    translate_topic,
)

st.set_page_config(
    page_title="神经网络领域文献追踪看板 / NN Literature Tracker",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

CUSTOM_PREFIX = "自定义｜"

# --------------------------------------------------------------------------
# 主题（跟随系统 / 白天 / 黑夜）
# --------------------------------------------------------------------------
_THEME_COMMON = """
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }
[data-testid="stExpander"] { border-radius: 10px; }
"""

_THEME_LIGHT = """
.stApp { background-color: #ffffff !important; }
[data-testid="stSidebar"] { background-color: #f0f2f6 !important; }
"""

_THEME_DARK = """
.stApp, section.main, .main { background-color: #0e1117 !important; }
[data-testid="stSidebar"] { background-color: #161a24 !important; }
[data-testid="stSidebar"] * { color: #e6e8ee; }
h1, h2, h3, h4, h5, h6, p, span, label, li, .stMarkdown { color: #e6e8ee; }
[data-testid="stMetricLabel"] { color: #9aa4b2 !important; }
[data-testid="stMetricValue"] { color: #fafafa !important; }
div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #161a24 !important;
    border: 1px solid #2a2f3a !important;
}
[data-testid="stExpander"] details {
    background-color: #161a24 !important;
    border-color: #2a2f3a !important;
}
.stTextInput input, .stNumberInput input, .stTextArea textarea {
    background-color: #1c2230 !important;
    color: #e6e8ee !important;
    border-color: #2a2f3a !important;
}
div[data-baseweb="select"] > div {
    background-color: #1c2230 !important;
    color: #e6e8ee !important;
}
div[data-baseweb="menu"], div[data-baseweb="popover"] {
    background-color: #1c2230 !important;
}
hr { border-color: #2a2f3a !important; }
"""


def inject_theme(mode: str) -> None:
    """注入主题样式。

    「跟随系统」不依赖 JS：把深色样式整段包进 ``@media (prefers-color-scheme: dark)``，
    浏览器会自动按操作系统的深浅色偏好应用。
    """
    if mode == "dark":
        css = _THEME_DARK
    elif mode == "light":
        css = _THEME_LIGHT
    else:
        css = "@media (prefers-color-scheme: dark) {" + _THEME_DARK + "}"
    st.markdown(f"<style>{_THEME_COMMON}{css}</style>", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
OPEN_SOURCE_OPTIONS = ["all", "yes", "no", "unknown"]
OPEN_SOURCE_BADGE = {
    "yes": "🟢 {label}",
    "no": "🔴 {label}",
    "unknown": "⚪ {label}",
}


def _direction_label(key: str) -> str:
    """预置方向取中文名；自定义主题词原样显示（本身已可读）。"""
    return NAME_BY_KEY.get(key, key)


# --------------------------------------------------------------------------
# 侧边栏：语言 + 主题（必须最靠前，后面的文案都依赖 lang）
# --------------------------------------------------------------------------
_current_lang = st.session_state.get("ui_lang", DEFAULT_UI_LANG)
if _current_lang not in UI_LANGS:
    _current_lang = DEFAULT_UI_LANG

with st.sidebar:
    st.radio(
        t(_current_lang, "ui_language"),
        options=list(UI_LANGS.keys()),
        format_func=lambda code: UI_LANGS[code],
        horizontal=True,
        key="ui_lang",
    )

lang: str = st.session_state.get("ui_lang", DEFAULT_UI_LANG)
if lang not in UI_LANGS:
    lang = DEFAULT_UI_LANG

with st.sidebar:
    if st.session_state.get("theme_mode") not in ("system", "light", "dark"):
        st.session_state["theme_mode"] = "system"
    theme_mode: str = st.radio(
        t(lang, "theme_label"),
        options=["system", "light", "dark"],
        format_func=lambda m: t(lang, f"theme_{m}"),
        horizontal=True,
        key="theme_mode",
    )

inject_theme(theme_mode)


# --------------------------------------------------------------------------
# 侧边栏：自定义主题词（不受 13 个方向限制）
# --------------------------------------------------------------------------
st.session_state.setdefault("custom_topics", [])

with st.sidebar:
    st.divider()
    st.subheader(t(lang, "topic_title"))
    st.caption(t(lang, "topic_help"))

    topic_input: str = st.text_input(
        t(lang, "topic_input_label"),
        placeholder=t(lang, "topic_placeholder"),
        key="topic_field",
    )

    if st.button(t(lang, "topic_add_button"), use_container_width=True):
        label = (topic_input or "").strip()
        term, source = translate_topic(label)
        if term:
            new_key = f"{CUSTOM_PREFIX}{label or term}"
            topics = st.session_state["custom_topics"]
            if not any(item["key"] == new_key for item in topics):
                topics.append({"key": new_key, "label": label or term, "term": term})
            st.session_state["topic_msg"] = ("ok", label or term, term, source)
        else:
            st.session_state["topic_msg"] = ("fail", label, "", source)
        st.rerun()

    _msg = st.session_state.get("topic_msg")
    if _msg:
        if _msg[0] == "ok":
            st.success(t(lang, "topic_added", label=_msg[1], term=_msg[2]))
        else:
            st.error(t(lang, "topic_failed"))

    _topics = st.session_state.get("custom_topics", [])
    st.caption(t(lang, "topic_added_title"))
    if not _topics:
        st.caption(t(lang, "topic_none"))
    for _index, _topic in enumerate(list(_topics)):
        _col_name, _col_del = st.columns([5, 1])
        _col_name.caption(f"• {_topic['label']} → `{_topic['term']}`")
        if _col_del.button("✕", key=f"rmtopic_{_index}", help=t(lang, "topic_remove")):
            _topics.pop(_index)
            st.rerun()


# --------------------------------------------------------------------------
# 侧边栏：追踪设置
# --------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.subheader(t(lang, "settings_title"))

    selected_keys: List[str] = st.multiselect(
        t(lang, "direction_label"),
        options=ALL_KEYS,
        default=["transformer_llm", "cnn_vision"],
        format_func=_direction_label,
        help=t(lang, "direction_help"),
    )

    for key in selected_keys:
        st.caption(f"· {_direction_label(key)}：{DESC_BY_KEY.get(key, '')}")

    years: float = st.number_input(
        t(lang, "days_label"),
        min_value=0.1,
        max_value=10.0,
        value=DEFAULT_YEARS,
        step=0.1,
        format="%.1f",
        help=t(lang, "days_help"),
    )
    # 界面按「年」输入，内部仍按天换算，避免改动下游所有时间逻辑
    days: int = max(1, int(round(float(years) * 365.25)))
    st.caption(t(lang, "years_approx", days=days))

    max_results: int = st.number_input(
        t(lang, "max_label"),
        min_value=5,
        max_value=200,
        value=DEFAULT_MAX_RESULTS,
        step=5,
        help=t(lang, "max_help"),
    )

    llm_ready = is_llm_configured()
    use_llm: bool = st.checkbox(
        t(lang, "llm_toggle"), value=llm_ready, help=t(lang, "llm_help")
    )
    if not llm_ready:
        st.warning(t(lang, "key_missing"), icon="🔑")

    st.divider()
    fetch_clicked = st.button(
        t(lang, "fetch_button"), type="primary", use_container_width=True
    )


# --------------------------------------------------------------------------
# 侧边栏：检索（显式搜索按钮）
# --------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.subheader(t(lang, "filters_title"))

    with st.form("search_form"):
        keyword_field: str = st.text_input(
            t(lang, "search_label"),
            placeholder=t(lang, "search_placeholder"),
            help=t(lang, "search_help"),
        )
        search_submitted = st.form_submit_button(
            t(lang, "search_button"), use_container_width=True
        )

    if search_submitted:
        applied = (keyword_field or "").strip()
        st.session_state["kw_applied"] = applied
        if applied:
            cached = get_keyword_cache(applied)
            if cached and cached.get("dst") and has_cjk(applied):
                st.session_state["kw_terms"] = [
                    x for x in str(cached["dst"]).split("|") if x
                ]
                st.session_state["kw_src"] = cached.get("source") or "dict"
            else:
                terms, source = translate_keyword_terms(applied)
                st.session_state["kw_terms"] = terms
                st.session_state["kw_src"] = source
                if terms:
                    save_keyword_cache(applied, "|".join(terms), source)
        else:
            st.session_state["kw_terms"] = []
            st.session_state["kw_src"] = "empty"

    applied_keyword: str = st.session_state.get("kw_applied", "")
    applied_terms: List[str] = st.session_state.get("kw_terms", [])
    keyword_source: str = st.session_state.get("kw_src", "empty")

    if keyword_source in ("dict", "llm") and applied_terms:
        st.caption(
            t(lang, "kw_translated", terms=", ".join(applied_terms))
            + " "
            + t(lang, "kw_translated_hint")
        )
    elif keyword_source == "failed":
        st.caption(t(lang, "kw_untranslated"))

    st.caption(t(lang, "search_hint"))

    open_source: str = st.radio(
        t(lang, "os_label"),
        options=OPEN_SOURCE_OPTIONS,
        format_func=lambda x: t(lang, f"os_{x}"),
    )

    _counts = category_counts()
    _custom_db_keys = [k for k in _counts if k not in NAME_BY_KEY]
    view_category: str = st.selectbox(
        t(lang, "cat_label"),
        options=["all"] + ALL_KEYS + _custom_db_keys,
        format_func=lambda x: t(lang, "cat_all") if x == "all" else _direction_label(x),
    )

    show_limit: int = st.slider(
        t(lang, "limit_label"), 10, 300, DEFAULT_FETCH_LIMIT, 10
    )

    show_abstract: bool = st.checkbox(t(lang, "show_abstract"), value=False)


# --------------------------------------------------------------------------
# 侧边栏：摘要翻译语言
# --------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.subheader(t(lang, "translate_title"))

    _lang_options = ["none"] + list(ABSTRACT_LANGS.keys())
    if st.session_state.get("translate_lang") not in _lang_options:
        st.session_state["translate_lang"] = "zh" if llm_ready else "none"

    translate_lang: str = st.selectbox(
        t(lang, "translate_lang_label"),
        options=_lang_options,
        format_func=lambda code: t(lang, "translate_none")
        if code == "none"
        else lang_display(code),
        help=t(lang, "translate_help"),
        key="translate_lang",
    )


# --------------------------------------------------------------------------
# 侧边栏：数据管理
# --------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    with st.expander(t(lang, "data_title")):
        st.caption(
            t(lang, "caption_model_key", model=DEEPSEEK_MODEL, key=masked_key())
        )
        if st.button(t(lang, "log_button")):
            st.session_state["show_log"] = not st.session_state.get("show_log", False)

        if _counts:
            st.caption(t(lang, "inventory_title"))
            for key, num in sorted(_counts.items(), key=lambda kv: -kv[1]):
                st.caption(
                    t(lang, "inventory_item", name=_direction_label(key), count=num)
                )

        confirm_clear = st.checkbox(t(lang, "clear_confirm"))
        if st.button(t(lang, "clear_button"), disabled=not confirm_clear):
            clear_all()
            for stale in ("last_stats", "kw_applied", "kw_terms", "kw_src", "topic_msg"):
                st.session_state.pop(stale, None)
            st.session_state["custom_topics"] = []
            st.success(t(lang, "cleared_toast"))
            st.rerun()

    st.divider()
    st.caption(t(lang, "sidebar_footer"))


# --------------------------------------------------------------------------
# 主区域：标题与统计
# --------------------------------------------------------------------------
st.title(t(lang, "app_title"))
st.caption(t(lang, "app_caption"))

overview = get_overview()

col1, col2, col3, col4 = st.columns(4)
col1.metric(t(lang, "metric_total"), overview["total"])
col2.metric(t(lang, "metric_structured"), overview["structured"])
col3.metric(t(lang, "metric_open"), overview["open_source"])
_last_fetch = str(overview["last_fetch"])
col4.metric(
    t(lang, "metric_last_fetch"),
    _last_fetch[:16].replace("T", " ") if _last_fetch != "—" else "—",
)

if overview["failed"]:
    st.caption(t(lang, "failed_caption", n=overview["failed"]))


# --------------------------------------------------------------------------
# 抓取动作
# --------------------------------------------------------------------------
if fetch_clicked:
    _topics_now = st.session_state.get("custom_topics", [])
    if not selected_keys and not _topics_now:
        st.error(t(lang, "need_direction"))
    else:
        progress_bar = st.progress(0.0, text="…")

        def _on_progress(pct: float, message: str) -> None:
            progress_bar.progress(min(max(pct, 0.0), 1.0), text=message)

        try:
            stats = run_pipeline(
                category_keys=selected_keys,
                days=days,
                max_results_per_category=int(max_results),
                use_llm=use_llm,
                progress=_on_progress,
                custom_topics=_topics_now,
            )
            st.session_state["last_stats"] = stats.as_dict()
            st.session_state["last_summary"] = stats.summary()
            progress_bar.progress(1.0, text="100%")
        except Exception as exc:  # 最外层兜底：任何异常都不该让页面白屏
            progress_bar.empty()
            st.error(t(lang, "refresh_failed", error=exc))
            st.exception(exc)

        st.rerun()

last_stats: Optional[Dict[str, Any]] = st.session_state.get("last_stats")
if last_stats:
    st.success(t(lang, "last_result", summary=st.session_state.get("last_summary", "")))
    errors = last_stats.get("errors") or []
    if errors:
        with st.expander(t(lang, "warnings_expander", n=len(errors))):
            for item in errors[:30]:
                st.text(item)
            if len(errors) > 30:
                st.text(t(lang, "more_warnings", n=len(errors) - 30))

if st.session_state.get("show_log"):
    with st.expander(t(lang, "log_title"), expanded=True):
        logs = get_fetch_log(20)
        if not logs:
            st.caption(t(lang, "no_log"))
        for item in logs:
            st.text(
                t(
                    lang,
                    "log_line",
                    flag="✅" if item["ok"] else "❌",
                    time=item["created_at"],
                    category=_direction_label(item["category_key"]),
                    days=item["days"],
                    fetched=item["fetched"],
                    kept=item["kept"],
                )
                + (f" | {item['error']}" if item["error"] else "")
            )

st.divider()


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------
rows = query_papers(
    keyword=applied_keyword,
    keywords=applied_terms,
    open_source=open_source,
    category_key=view_category,
    days=days,
    limit=int(show_limit),
)

translator = Translator()


# --------------------------------------------------------------------------
# 渲染辅助
# --------------------------------------------------------------------------
def _export_csv(rows_: List[Dict[str, Any]], target_lang: str) -> bytes:
    """把当前结果导出为 UTF-8 BOM 的 CSV（Excel 直接双击可读）。"""
    records = []
    for row in rows_:
        record = {
            "arxiv_id": row["arxiv_id"],
            "标题 / title": row["title"],
            "发布时间 / published": (row["published"] or "")[:10],
            "主类目 / category": row["primary_category"],
            "归属方向 / group": " · ".join(
                _direction_label(k) for k in row["category_keys"]
            ),
            "一句话核心贡献 / contribution": row["one_line_contribution"] or "",
            "数据集方法 / datasets": "、".join(row["datasets_methods"]),
            "是否开源 / open_source": row["code_open_source"] or "unknown",
            "代码链接 / code_url": row["code_url"] or "",
            "链接 / url": row["abs_url"],
        }
        if target_lang != "none":
            cached = get_translation(row["arxiv_id"], target_lang)
            record[f"译文 / translation ({target_lang})"] = (
                cached["content"] if cached else ""
            )
        records.append(record)
    return pd.DataFrame(records).to_csv(index=False).encode("utf-8-sig")


def _translate_and_store(row: Dict[str, Any], target_lang: str) -> None:
    """调用模型翻译摘要并落库；成功后 rerun 让界面显示译文。"""
    with st.spinner(t(lang, "translating")):
        try:
            text = translator.translate_abstract(row["abstract"] or "", target_lang)
            save_translation(row["arxiv_id"], target_lang, text, DEEPSEEK_MODEL)
        except Exception as exc:
            st.error(t(lang, "translate_failed", error=exc))
            return
    st.rerun()


def _render_translation_flat(row: Dict[str, Any], target_lang: str) -> None:
    """扁平版的摘要翻译块：一行按钮或一段译文，不放进折叠面板。"""
    if target_lang == "none":
        return
    if not translator.available:
        st.caption(t(lang, "translate_need_key"))
        return
    if not (row["abstract"] or "").strip():
        return

    aid = row["arxiv_id"]
    cached = get_translation(aid, target_lang)

    if cached and cached.get("content"):
        st.markdown(t(lang, "translated_label", lang=lang_display(target_lang)))
        st.write(cached["content"])
        if st.button(t(lang, "retranslate_button"), key=f"retr_{target_lang}_{aid}"):
            _translate_and_store(row, target_lang)
    else:
        if st.button(
            t(lang, "translate_button", lang=lang_display(target_lang)),
            key=f"tr_{target_lang}_{aid}",
        ):
            _translate_and_store(row, target_lang)


def _render_row(
    index: int,
    row: Dict[str, Any],
    target_lang: str,
    with_abstract: bool,
) -> None:
    """扁平列表渲染：一篇论文一段，段间只用分隔线，不套卡片、不套折叠面板。

    这样在 200 条结果时视觉上是一份连续的清单，而不是层层嵌套的方框。
    """
    st.markdown(f"**{index}. {row['title']}**")

    authors = row["authors"] or ""
    if len(authors) > 80:
        authors = authors[:80] + " …"

    meta_parts = [
        (row["published"] or "")[:10],
        row["primary_category"] or "",
        " · ".join(_direction_label(k) for k in row["category_keys"]),
    ]
    st.caption(" ｜ ".join(part for part in meta_parts if part))

    contribution = row.get("one_line_contribution")
    if contribution:
        st.markdown(t(lang, "card_contribution", text=contribution))
    else:
        st.markdown(t(lang, "card_not_structured"))

    datasets = row.get("datasets_methods") or []
    if datasets:
        st.markdown(t(lang, "card_datasets", tags=" ".join(f"`{x}`" for x in datasets)))
    else:
        st.markdown(t(lang, "card_not_datasets"))

    os_key = row.get("code_open_source") or "unknown"
    badge = OPEN_SOURCE_BADGE.get(os_key, OPEN_SOURCE_BADGE["unknown"]).format(
        label=t(lang, f"badge_{os_key}")
    )
    links = [
        f"[{t(lang, 'card_arxiv')}]({row['abs_url']})",
        f"[{t(lang, 'card_pdf')}]({row['pdf_url']})",
    ]
    if row.get("code_url"):
        links.append(f"[{t(lang, 'card_code')}]({row['code_url']})")
    st.markdown(badge + "　" + " · ".join(links))

    if authors:
        st.caption(f"👥 {authors}")

    status = row.get("parse_status") or ""
    if status and status != "ok":
        st.caption(
            t(
                lang,
                "parse_status_prefix",
                status=status,
                hint=status_hint(lang, status),
            )
        )

    if with_abstract:
        st.caption(row["abstract"] or t(lang, "no_abstract"))

    _render_translation_flat(row, target_lang)

    st.divider()


# --------------------------------------------------------------------------
# 结果头部 + 导出
# --------------------------------------------------------------------------
header_left, header_right = st.columns([3, 1])
with header_left:
    st.subheader(t(lang, "results_title", n=len(rows)))
with header_right:
    if rows:
        st.download_button(
            t(lang, "export_button"),
            data=_export_csv(rows, translate_lang),
            file_name=f"nn_papers_{years}y_{translate_lang}.csv",
            mime="text/csv",
            use_container_width=True,
        )

if not rows:
    if overview["total"] == 0:
        st.info(t(lang, "empty_db"))
    else:
        st.info(t(lang, "empty_filter"))
    st.stop()

for _idx, paper_row in enumerate(rows, start=1):
    _render_row(_idx, paper_row, translate_lang, show_abstract)

st.caption(t(lang, "data_source"))
