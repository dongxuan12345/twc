# -*- coding: utf-8 -*-
"""界面文案的多语言表（i18n）。

设计说明
--------
* **默认中文**：``DEFAULT_UI_LANG = "zh"``，未做任何选择时页面全中文。
* 文案集中在此文件，``app.py`` 里不出现任何硬编码中文，这样新增一种语言
  只需要往 ``STRINGS`` 里加一份字典，不用改界面代码。
* 找不到 key 时按「目标语言 → 中文 → key 本身」逐级回退，保证不会因为漏译
  而让界面显示空白或抛 KeyError。
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULT_UI_LANG = "zh"

# 界面语言：键是内部标识，值是下拉框里显示的名字
UI_LANGS: Dict[str, str] = {
    "zh": "中文",
    "en": "English",
}

STRINGS: Dict[str, Dict[str, str]] = {
    # ==================== 中文（默认）====================
    "zh": {
        # ---- 侧边栏 ----
        "ui_language": "界面语言",
        "theme_label": "主题",
        "theme_system": "跟随系统",
        "theme_light": "白天",
        "theme_dark": "黑夜",
        "settings_title": "⚙️ 追踪设置",
        "direction_label": "神经网络功能方向（可多选）",
        "direction_help": "按功能切分的细分领域。多选时每个方向独立抓取，互不影响。",
        "days_label": "时间窗口（年）",
        "days_help": "以「年」为单位，可填小数（如 0.5 年 = 半年，0.6 年 ≈ 7 个月）。",
        "years_unit": "年",
        "years_approx": "≈ {days} 天",
        "show_abstract": "显示英文摘要",
        "max_label": "每个方向最多抓取篇数",
        "max_help": "arXiv 建议单次不超过 100 篇；抓取越多，LLM 提取耗时越长。",
        "llm_toggle": "启用 LLM 结构化提取",
        "llm_help": "关闭后只抓取论文，看板仅展示原始摘要。",
        "key_missing": "未检测到可用的 `DEEPSEEK_API_KEY`。\n\n复制 `.env.example` 为 `.env` 并填入 Key 后重启即可启用结构化提取与翻译。",
        "fetch_button": "🚀 抓取最新文献",

        # ---- 检索与筛选 ----
        "filters_title": "🔎 筛选与检索",
        "search_label": "关键词搜索（支持中文）",
        "search_placeholder": "如 扩散模型 / 图神经网络 / diffusion",
        "search_help": "输入中文会自动翻译成英文再检索，中英文结果都会返回。",
        "search_button": "🔍 搜索",
        "search_hint": "输入后点「搜索」才会生效；留空表示不按关键词筛选。",

        # ---- 自定义主题词 ----
        "topic_title": "➕ 自定义主题词",
        "topic_help": "不局限于下面 13 个方向，任何研究主题都能录进来；输入中文会自动翻成英文检索词。",
        "topic_input_label": "主题词（支持中文）",
        "topic_placeholder": "如：电池寿命预测 / 蛋白质结构预测",
        "topic_add_button": "翻译并加入追踪",
        "topic_added": "✅ 已加入：{label} → {term}",
        "topic_failed": "❌ 无法翻译该主题词（未配置 Key 且内置词典没覆盖）。请直接输入英文再试。",
        "topic_added_title": "已加入的自定义主题词：",
        "topic_none": "（暂无，可从上面的输入框添加）",
        "topic_remove": "移除",
        "kw_translated": "🔤 已自动翻译为：{terms}",
        "kw_translated_hint": "（将同时用中文与英文检索）",
        "kw_untranslated": "⚠️ 这个中文词没有命中内置词典，且当前无法调用翻译服务，已按原文检索。",
        "os_label": "代码开源状态",
        "os_all": "全部",
        "os_yes": "仅开源 (Yes)",
        "os_no": "仅未开源 (No)",
        "os_unknown": "状态未知 (Unknown)",
        "cat_label": "只看某个功能方向",
        "cat_all": "全部方向",
        "limit_label": "最多展示条数",
        "badge_yes": "开源 Yes",
        "badge_no": "未开源 No",
        "badge_unknown": "未知 Unknown",
        "topic_badge": "自定义",

        # ---- 摘要翻译 ----
        "translate_title": "🌐 摘要翻译",
        "translate_lang_label": "摘要翻译目标语言",
        "translate_none": "不翻译（只看原文）",
        "translate_help": "选定语言后，每张卡片内会出现「翻译此篇」按钮；译文会缓存到本地数据库，不会重复计费。",

        # ---- 数据管理 ----
        "data_title": "🗄️ 数据管理",
        "caption_model_key": "模型：`{model}`　Key：`{key}`",
        "log_button": "查看最近抓取日志",
        "inventory_title": "各方向库存：",
        "inventory_item": "· {name}：{count} 篇",
        "clear_confirm": "我确认要清空本地数据库",
        "clear_button": "清空数据库",
        "cleared_toast": "已清空",
        "sidebar_footer": "课程作业 · PRD / TDD / 编码验证全流程演示",

        # ---- 主区域 ----
        "app_title": "🧠 神经网络领域文献追踪看板",
        "app_caption": "按「功能方向」追踪 arXiv 最新论文 → LLM 结构化提炼为【一句话核心贡献】【数据集/方法】【代码是否开源】→ 支持中文关键词自动翻译、摘要多语言翻译与开源状态筛选",
        "metric_total": "库中论文",
        "metric_structured": "已结构化",
        "metric_open": "开源论文",
        "metric_last_fetch": "最近抓取",
        "failed_caption": "⚠️ 有 {n} 篇结构化提取失败，下次刷新会自动重试。",
        "need_direction": "请至少选择一个神经网络功能方向。",
        "refresh_failed": "刷新失败：{error}",
        "last_result": "上次刷新结果：{summary}",
        "warnings_expander": "⚠️ {n} 条警告（不影响其余数据）",
        "more_warnings": "…… 另有 {n} 条，详见数据库 fetch_log 表",
        "log_title": "📜 最近抓取日志",
        "no_log": "暂无日志",
        "log_line": "{flag} {time} | {category} | {days}天 | 抓取{fetched}篇/入库{kept}篇",
        "results_title": "📄 共 {n} 条结果",
        "export_button": "⬇️ 导出 CSV",
        "empty_db": "本地库还是空的。请在左侧选择功能方向与时间窗口，然后点击 **🚀 抓取最新文献**。\n\n首次运行流程：抓取 arXiv（每个方向约 3 秒限流）→ 逐篇调用 LLM 结构化 → 写入本地 SQLite。",
        "empty_filter": "当前筛选条件下没有匹配的论文，试着放宽关键词、时间窗口或开源状态。",

        # ---- 卡片 ----
        "card_contribution": "💡 **一句话核心贡献**：{text}",
        "card_not_structured": "💡 **一句话核心贡献**：_尚未结构化，见下方原文摘要_",
        "card_datasets": "🏷️ **数据集 / 方法**：{tags}",
        "card_not_datasets": "🏷️ **数据集 / 方法**：_未提取到_",
        "card_code": "代码仓库",
        "card_arxiv": "arXiv",
        "card_pdf": "PDF",
        "parse_status_prefix": "⚠️ 解析状态：{status} {hint}",
        "abstract_expander": "📖 查看摘要与提取证据",
        "abstract_original": "摘要原文（英文）",
        "no_abstract": "（无摘要）",
        "translate_button": "🌐 翻译为{lang}",
        "retranslate_button": "🔄 重新翻译",
        "translated_label": "译文（{lang}）",
        "translating": "正在翻译…",
        "translate_failed": "翻译失败：{error}",
        "translate_need_key": "翻译功能需要在 `.env` 中配置 `DEEPSEEK_API_KEY`。",
        "evidence_label": "提取证据（模型引用的原文句）",
        "model_caption": "模型：{model} ｜ 提取时间：{time}",
        "data_source": "数据来源：arXiv API（https://export.arxiv.org/api/query）　·　结构化结果与大模型译文仅供参考，请以原文为准。",

        # ---- 解析状态说明 ----
        "status_ok": "",
        "status_repaired": "（JSON 首次解析失败，重试后成功）",
        "status_fallback": "（结构化提取失败，已降级展示原文）",
        "status_failed": "（提取失败，下次刷新会重试）",
    },

    # ==================== English ====================
    "en": {
        "ui_language": "Language",
        "theme_label": "Theme",
        "theme_system": "System",
        "theme_light": "Light",
        "theme_dark": "Dark",
        "settings_title": "⚙️ Tracking settings",
        "direction_label": "Neural-network sub-fields (multi-select)",
        "direction_help": "Functional sub-fields. Each selected field is fetched independently.",
        "days_label": "Time window (years)",
        "days_help": "In years; decimals allowed (0.5 y = half a year, 0.6 y ≈ 7 months).",
        "years_unit": "years",
        "years_approx": "≈ {days} days",
        "show_abstract": "Show English abstract",
        "max_label": "Max papers per sub-field",
        "max_help": "arXiv recommends at most 100 per request. More papers means longer LLM extraction.",
        "llm_toggle": "Enable LLM structured extraction",
        "llm_help": "When off, papers are fetched but only the original abstract is shown.",
        "key_missing": "No usable `DEEPSEEK_API_KEY` found.\n\nCopy `.env.example` to `.env`, fill in your key, and restart to enable extraction and translation.",
        "fetch_button": "🚀 Fetch latest papers",

        "filters_title": "🔎 Search & filter",
        "search_label": "Keyword search (Chinese supported)",
        "search_placeholder": "e.g. 扩散模型 / graph neural network / diffusion",
        "search_help": "Chinese input is auto-translated to English; both Chinese and English results are returned.",
        "search_button": "🔍 Search",
        "search_hint": "Takes effect only after you press Search. Leave empty to skip keyword filtering.",

        "topic_title": "➕ Custom topic",
        "topic_help": "Not limited to the 13 sub-fields below — type any research topic; Chinese is auto-translated to an English query.",
        "topic_input_label": "Topic (Chinese supported)",
        "topic_placeholder": "e.g. battery lifetime prediction",
        "topic_add_button": "Translate & add",
        "topic_added": "✅ Added: {label} → {term}",
        "topic_failed": "❌ Cannot translate this topic (no API key and not covered by the built-in dictionary). Please type English directly.",
        "topic_added_title": "Added custom topics:",
        "topic_none": "(none yet — add one above)",
        "topic_remove": "Remove",
        "kw_translated": "🔤 Auto-translated to: {terms}",
        "kw_translated_hint": "(searching with both Chinese and English)",
        "kw_untranslated": "⚠️ This Chinese term is not in the built-in dictionary and translation is unavailable; searched as-is.",
        "os_label": "Code open-source status",
        "os_all": "All",
        "os_yes": "Open source only (Yes)",
        "os_no": "Closed source only (No)",
        "os_unknown": "Unknown status",
        "cat_label": "Filter by sub-field",
        "cat_all": "All sub-fields",
        "limit_label": "Max results to display",
        "badge_yes": "Open Yes",
        "badge_no": "Closed No",
        "badge_unknown": "Unknown",
        "topic_badge": "Custom",

        "translate_title": "🌐 Abstract translation",
        "translate_lang_label": "Translate abstracts into",
        "translate_none": "No translation (original only)",
        "translate_help": "After choosing a language, each card shows a 'Translate' button. Translations are cached locally and never billed twice.",

        "data_title": "🗄️ Data",
        "caption_model_key": "Model: `{model}`　Key: `{key}`",
        "log_button": "Show recent fetch log",
        "inventory_title": "Papers per sub-field:",
        "inventory_item": "· {name}: {count}",
        "clear_confirm": "I confirm clearing the local database",
        "clear_button": "Clear database",
        "cleared_toast": "Cleared",
        "sidebar_footer": "Course project · PRD / TDD / implementation walkthrough",

        "app_title": "🧠 Neural Network Literature Tracker",
        "app_caption": "Track the latest arXiv papers by functional sub-field → LLM distills each abstract into [one-line contribution] [datasets/methods] [open-source?] → Chinese keyword auto-translation, multi-language abstract translation and open-source filtering",
        "metric_total": "Papers stored",
        "metric_structured": "Structured",
        "metric_open": "Open source",
        "metric_last_fetch": "Last fetch",
        "failed_caption": "⚠️ {n} paper(s) failed structured extraction; they will be retried on the next refresh.",
        "need_direction": "Please select at least one sub-field.",
        "refresh_failed": "Refresh failed: {error}",
        "last_result": "Last refresh: {summary}",
        "warnings_expander": "⚠️ {n} warning(s) — the rest of the data is unaffected",
        "more_warnings": "… {n} more, see the fetch_log table",
        "log_title": "📜 Recent fetch log",
        "no_log": "No log yet",
        "log_line": "{flag} {time} | {category} | {days}d | fetched {fetched} / kept {kept}",
        "results_title": "📄 {n} result(s)",
        "export_button": "⬇️ Export CSV",
        "empty_db": "The local database is empty. Pick sub-fields and a time window on the left, then click **🚀 Fetch latest papers**.\n\nFirst run: fetch arXiv (~3 s rate limit per sub-field) → LLM extraction → write to local SQLite.",
        "empty_filter": "No papers match the current filters. Try a broader keyword, a longer time window, or another open-source status.",

        "card_contribution": "💡 **One-line contribution**: {text}",
        "card_not_structured": "💡 **One-line contribution**: _not structured yet — see the abstract below_",
        "card_datasets": "🏷️ **Datasets / methods**: {tags}",
        "card_not_datasets": "🏷️ **Datasets / methods**: _not extracted_",
        "card_code": "Code",
        "card_arxiv": "arXiv",
        "card_pdf": "PDF",
        "parse_status_prefix": "⚠️ Parse status: {status} {hint}",
        "abstract_expander": "📖 Abstract & evidence",
        "abstract_original": "Original abstract (EN)",
        "no_abstract": "(no abstract)",
        "translate_button": "🌐 Translate to {lang}",
        "retranslate_button": "🔄 Re-translate",
        "translated_label": "Translation ({lang})",
        "translating": "Translating…",
        "translate_failed": "Translation failed: {error}",
        "translate_need_key": "Translation requires `DEEPSEEK_API_KEY` in `.env`.",
        "evidence_label": "Evidence (quoted from the abstract)",
        "model_caption": "Model: {model} ｜ Extracted at: {time}",
        "data_source": "Source: arXiv API (https://export.arxiv.org/api/query) ｜ LLM output is for reference only — always verify against the original paper.",

        "status_ok": "",
        "status_repaired": "(first JSON parse failed, succeeded on retry)",
        "status_fallback": "(extraction failed, showing the original abstract instead)",
        "status_failed": "(extraction failed, will retry on next refresh)",
    },
}


def t(lang: str, key: str, **kwargs: Any) -> str:
    """取一条界面文案。

    回退顺序：目标语言 → 中文 → key 本身，保证界面永不出现空字符串。
    """
    table = STRINGS.get(lang) or STRINGS[DEFAULT_UI_LANG]
    text = table.get(key)
    if text is None:
        text = STRINGS[DEFAULT_UI_LANG].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # 占位符对不上时宁可少格式化，也不要让页面崩掉
            return text
    return text


def status_hint(lang: str, status: str) -> str:
    """解析状态的自然语言说明。未知状态返回空串而不是报错。"""
    mapping = {
        "ok": "status_ok",
        "repaired": "status_repaired",
        "fallback": "status_fallback",
        "failed": "status_failed",
    }
    key = mapping.get(status or "")
    return t(lang, key) if key else ""
