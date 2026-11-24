# -*- coding: utf-8 -*-
"""纯离线冒烟测试：不联网、不调用大模型、不写数据库。

覆盖的是「最容易出错、又最不该出错」的纯函数：
    * arXiv 检索式与时间窗口换算
    * Atom 字段清洗（id 去版本号、时间格式统一）
    * JSON 容错解析（代码块 / 前置废话 / 尾逗号 / 花括号嵌套 / 彻底非法）
    * 字段归一化与防幻觉校验
    * 界面中英文案表的 key 对齐、回退链
    * 中文检索词的内置词典翻译（不触发任何网络请求）

运行：
    python tests/smoke_test.py
退出码 0 表示全部通过，1 表示有失败用例（可直接用于 CI / 提交前自检）。
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.arxiv_client import (  # noqa: E402
    Paper,
    _clean,
    _extract_arxiv_id,
    _norm_datetime,
    build_date_range,
    build_search_query,
    keyword_match,
)
from src.llm_extractor import (  # noqa: E402
    JSONParseError,
    _normalize_datasets,
    _normalize_open_source,
    _normalize_url,
    _url_supported_by_source,
    parse_structured_output,
)
from src.storage import cutoff_iso  # noqa: E402
from src.i18n import STRINGS, status_hint, t  # noqa: E402
from src.translator import (  # noqa: E402
    dict_lookup,
    has_cjk,
    lang_display,
    translate_keyword_terms,
)

CASES = []


def case(name):
    """注册一个测试用例。"""

    def decorator(fn):
        CASES.append((name, fn))
        return fn

    return decorator


# --------------------------------------------------------------------------
# 1. arXiv 检索式与时间窗口
# --------------------------------------------------------------------------
@case("时间窗口换算为 UTC 绝对区间")
def test_build_date_range():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    rng, start, end = build_date_range(7, now=now)
    assert rng == "[202611161200 TO 202611231200]", rng
    assert start.day == 16 and end.day == 23


@case("search_query 拼接格式正确")
def test_build_search_query():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    query = build_search_query("cs.CV", 7, now=now)
    assert query == "cat:cs.CV AND submittedDate:[202611161200 TO 202611231200]", query
    assert "cat:" in query and "submittedDate:" in query


@case("days 小于 1 时被夹到 1，不产生负区间")
def test_build_date_range_guard():
    now = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)
    rng, start, _ = build_date_range(0, now=now)
    assert rng.startswith("[2026112200"), rng
    assert start.day == 22


# --------------------------------------------------------------------------
# 2. Atom 字段清洗
# --------------------------------------------------------------------------
@case("arxiv id 去除版本号")
def test_extract_arxiv_id():
    assert _extract_arxiv_id("http://arxiv.org/abs/2611.01234v2") == "2611.01234"
    assert _extract_arxiv_id("http://arxiv.org/abs/2611.01234v12") == "2611.01234"
    assert _extract_arxiv_id("https://arxiv.org/abs/cs/0601001v1") == "cs/0601001"
    assert _extract_arxiv_id("http://arxiv.org/abs/2611.01234") == "2611.01234"


@case("时间统一为 YYYY-MM-DDTHH:MM:SSZ")
def test_norm_datetime():
    assert _norm_datetime("2026-11-20T18:00:00Z") == "2026-11-20T18:00:00Z"
    assert _norm_datetime("2026-11-20T18:00:00+08:00") == "2026-11-20T10:00:00Z"
    assert _norm_datetime("") == ""


@case("空白压缩")
def test_clean():
    assert _clean("  a\n   b\t c ") == "a b c"
    assert _clean(None) == ""


@case("关键词匹配大小写不敏感")
def test_keyword_match():
    paper = Paper(
        arxiv_id="2611.00001",
        title="A Graph Neural Network for Molecules",
        abstract="We study message passing.",
        authors="A, B",
        published="2026-11-20T00:00:00Z",
        updated="2026-11-20T00:00:00Z",
        abs_url="https://arxiv.org/abs/2611.00001",
        pdf_url="https://arxiv.org/pdf/2611.00001",
        primary_category="cs.LG",
        all_categories="cs.LG",
        comment="",
        journal_ref="",
    )
    assert keyword_match(paper, ["graph neural network"]) is True
    assert keyword_match(paper, ["GRAPH"]) is True
    assert keyword_match(paper, ["diffusion model"]) is False
    assert keyword_match(paper, []) is True  # 空关键词视为不过滤


# --------------------------------------------------------------------------
# 3. JSON 容错解析（作业要求：JSON Decode Error 必须兜住）
# --------------------------------------------------------------------------
@case("标准 JSON 直接解析")
def test_parse_plain():
    data = parse_structured_output('{"one_line_contribution": "x", "code_open_source": "yes"}')
    assert data["one_line_contribution"] == "x"


@case("去掉 ```json 代码块后解析")
def test_parse_fenced():
    text = '```json\n{"one_line_contribution": "x"}\n```'
    assert parse_structured_output(text)["one_line_contribution"] == "x"


@case("模型前置废话（常见失败场景）也能解析")
def test_parse_with_preamble():
    text = '好的，以下是提取结果：\n{"one_line_contribution": "y"} \n希望对你有帮助。'
    assert parse_structured_output(text)["one_line_contribution"] == "y"


@case("尾逗号自动修复")
def test_parse_trailing_comma():
    assert parse_structured_output('{"a": 1,}')["a"] == 1


@case("字符串内部的 } 不会截断解析")
def test_parse_nested_brace_in_string():
    data = parse_structured_output('{"s": "value is {weird}", "n": 1}')
    assert data["s"] == "value is {weird}" and data["n"] == 1


@case("完全非 JSON 的输出抛出 JSONParseError（而不是让程序崩掉）")
def test_parse_invalid():
    for bad in ["抱歉，我无法完成这个任务", "", "   ", "{not json at all}"]:
        try:
            parse_structured_output(bad)
        except JSONParseError:
            continue
        raise AssertionError(f"应当抛出 JSONParseError，实际返回了结果：{bad!r}")


# --------------------------------------------------------------------------
# 4. 字段归一化与防幻觉
# --------------------------------------------------------------------------
@case("开源状态三态归一化")
def test_normalize_open_source():
    assert _normalize_open_source(True) == "yes"
    assert _normalize_open_source("YES") == "yes"
    assert _normalize_open_source("是") == "yes"
    assert _normalize_open_source(False) == "no"
    assert _normalize_open_source("否") == "no"
    assert _normalize_open_source("not available") == "no"
    assert _normalize_open_source(None) == "unknown"
    assert _normalize_open_source("") == "unknown"


@case("数据集字段清洗：去泛词、去空、去重、限量")
def test_normalize_datasets():
    assert _normalize_datasets(None) == []
    assert _normalize_datasets("QM9, ZINC; ETTh1、Weather") == [
        "QM9", "ZINC", "ETTh1", "Weather",
    ]
    assert _normalize_datasets(["deep learning", "GNN"]) == ["GNN"]
    assert _normalize_datasets(["A", "a", "A"]) == ["A"]
    assert len(_normalize_datasets([f"d{i}" for i in range(20)])) == 6


@case("从文本中提取代码仓库链接")
def test_normalize_url():
    assert _normalize_url("见 https://github.com/a/b.") == "https://github.com/a/b"
    assert _normalize_url(None) is None
    assert _normalize_url("没有链接") is None
    assert _normalize_url("https://example.com/not-a-repo") is None


@case("防幻觉：链接必须在摘要原文中出现过")
def test_url_supported_by_source():
    source = "Code is available at https://github.com/demo/net."
    assert _url_supported_by_source("https://github.com/demo/net", source) is True
    # 协议/www/末尾斜杠差异不该误判
    assert _url_supported_by_source("http://www.github.com/demo/net/", source) is True
    # 模型凭空捏造的仓库必须被判定为不支持
    assert _url_supported_by_source("https://github.com/fake/repo", source) is False


# --------------------------------------------------------------------------
# 5. 存储层纯函数
# --------------------------------------------------------------------------
@case("cutoff_iso 输出可直接字符串比较的 ISO8601")
def test_cutoff_iso():
    value = cutoff_iso(7)
    assert len(value) == 20 and value.endswith("Z"), value
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")  # 不抛异常即格式正确


# --------------------------------------------------------------------------
# 6. 界面多语言（v1.1）
# --------------------------------------------------------------------------
@case("中英文案表 key 完全对齐（防漏译）")
def test_i18n_key_parity():
    zh_keys = set(STRINGS["zh"].keys())
    en_keys = set(STRINGS["en"].keys())
    missing_in_en = zh_keys - en_keys
    missing_in_zh = en_keys - zh_keys
    assert not missing_in_en, f"英文缺少这些 key：{sorted(missing_in_en)}"
    assert not missing_in_zh, f"中文缺少这些 key：{sorted(missing_in_zh)}"


@case("未知语言回退到中文，未知 key 回退到 key 本身")
def test_i18n_fallback():
    assert t("zh", "app_title").startswith("🧠")
    assert t("fr_FR", "app_title") == t("zh", "app_title")   # 未支持的语言 → 中文
    assert t("zh", "no_such_key_xyz") == "no_such_key_xyz"    # 未定义的 key → 原样返回
    assert t("en", "results_title", n=3) == "📄 3 result(s)"
    assert t("zh", "results_title", n=3) == "📄 共 3 条结果"


@case("解析状态说明不会因未知状态报错")
def test_status_hint():
    assert status_hint("zh", "ok") == ""
    assert "重试" in status_hint("zh", "repaired")
    assert status_hint("zh", "unknown_status_xyz") == ""


# --------------------------------------------------------------------------
# 7. 中文检索词翻译（v1.1）
# --------------------------------------------------------------------------
@case("中文字符检测")
def test_has_cjk():
    assert has_cjk("扩散模型") is True
    assert has_cjk("diffusion model") is False
    assert has_cjk("PINN 物理信息") is True
    assert has_cjk("") is False


@case("内置词典命中：长词优先、不重复输出")
def test_dict_lookup():
    assert dict_lookup("扩散模型") == ["diffusion model"]
    # 「图神经网络」命中后不应再被「神经网络」重复命中
    assert dict_lookup("图神经网络的推理加速") == [
        "graph neural network", "inference acceleration",
    ]
    assert dict_lookup("完全不认识的词") == []


@case("中文检索词翻译：词典命中时不联网")
def test_translate_keyword_terms_dict():
    terms, source = translate_keyword_terms("扩散模型")
    assert source == "dict", source
    assert terms == ["diffusion model"]

    # 纯英文输入：无需翻译
    terms2, source2 = translate_keyword_terms("transformer")
    assert terms2 == [] and source2 == "ascii"


@case("目标语言显示名映射完整")
def test_lang_display():
    assert lang_display("zh") == "简体中文"
    assert lang_display("ja") == "日本語"
    assert lang_display("unknown_code") == "unknown_code"


# --------------------------------------------------------------------------
# 运行器
# --------------------------------------------------------------------------
def main() -> int:
    passed = 0
    failures = []

    for name, fn in CASES:
        try:
            fn()
        except Exception as exc:  # 用一个失败用例的完整堆栈定位问题
            failures.append((name, exc, traceback.format_exc()))
            print(f"[FAIL] {name}: {exc}")
        else:
            passed += 1
            print(f"[ ok ] {name}")

    total = len(CASES)
    print("-" * 60)
    print(f"通过 {passed}/{total}")

    if failures:
        print("\n失败详情：")
        for name, _exc, tb in failures:
            print(f"\n=== {name} ===\n{tb}")
        return 1

    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
