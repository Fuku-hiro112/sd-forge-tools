"""expander の {alt1;alt2;...} ランダム選択グループ機能のテスト.

既存の ; / // / $変数 による直積展開への影響が無いことも合わせて検証する。
"""
from __future__ import annotations

import re

from . import expander


# ====================================================
# 回帰: {} を含まない既存プロンプトの直積展開が変わらないこと
# ====================================================
def test_existing_cartesian_expansion_unchanged():
    results = expander.expand_prompts("a;b//c;d", {}, [])
    assert sorted(results) == sorted(["a,c", "a,d", "b,c", "b,d"])


def test_split_alternations_without_braces_matches_plain_split():
    # 波括弧を含まないテキストは text.split(";") と同じ挙動であること
    samples = ["a;b;c", "  x ; y  ", "single", "", "a;;b"]
    for text in samples:
        expected = [v.strip() for v in text.split(";") if v.strip() != ""]
        assert expander._split_alternations(text) == expected


# ====================================================
# 新機能: 生成枚数が変わらないこと（ユーザー確認シナリオ）
# ====================================================
def test_random_group_does_not_change_image_count():
    body = "a;b//{c;d}//e;f"
    results = expander.expand_prompts(body, {}, [])
    assert len(results) == 4


def test_random_group_preserves_outer_cartesian_patterns():
    body = "a;b//{c;d}//e;f"
    seen_patterns = set()
    for _ in range(50):
        results = expander.expand_prompts(body, {}, [])
        assert len(results) == 4
        for r in results:
            assert "{" not in r and "}" not in r and ";" not in r
            m = re.match(r"^(a|b),(c|d),(e|f)$", r)
            assert m is not None, f"unexpected result: {r!r}"
            seen_patterns.add((m.group(1), m.group(3)))
    assert seen_patterns == {("a", "e"), ("a", "f"), ("b", "e"), ("b", "f")}


def test_random_group_is_independent_per_generated_image():
    body = "a;b//{c;d}//e;f"
    middles: set[str] = set()
    for _ in range(80):
        results = expander.expand_prompts(body, {}, [])
        for r in results:
            middles.add(r.split(",")[1])
    # 十分な試行回数の中で c と d の両方が出現すること（毎回固定値に偏らない）
    assert middles == {"c", "d"}


def test_random_group_simple_two_choices():
    for _ in range(30):
        results = expander.expand_prompts("{c;d}", {}, [])
        assert results in (["c"], ["d"])


# ====================================================
# 後方互換: ; を含まない {} は無変更で残ること
# ====================================================
def test_legacy_n_notation_untouched():
    results = expander.expand_prompts("prompt {2} more", {}, [])
    assert results == ["prompt {2} more"]


def test_single_choice_brace_untouched():
    results = expander.expand_prompts("masterpiece, {best quality}", {}, [])
    assert results == ["masterpiece, {best quality}"]


def test_empty_brace_untouched():
    results = expander.expand_prompts("a {} b", {}, [])
    assert results == ["a {} b"]


# ====================================================
# ; の保護: 変数定義値の中の {} は分割対象にならないこと
# ====================================================
def test_semicolon_inside_braces_protected_in_variable_definition():
    parsed = expander.parse_main_prompt(
        "変数---\n$名前 = {a;b};c\n---\n$名前"
    )
    assert parsed.inline_vars["名前"] == ["{a;b}", "c"]


def test_semicolon_inside_braces_protected_in_inline_slot():
    slots = expander.parse_body_into_slots("//{a;b};c//")
    assert len(slots) == 1
    assert slots[0].alternatives == ["{a;b}", "c"]


# ====================================================
# ネスト範囲: //...// の中でも {} が使えること
# ====================================================
def test_random_group_inside_inline_slot():
    body = "x//{p;q}//y"
    for _ in range(30):
        results = expander.expand_prompts(body, {}, [])
        assert len(results) == 1
        assert results[0] in ("x,p,y", "x,q,y")


# ====================================================
# 変数展開との組み合わせ
# ====================================================
def test_random_group_with_variable_reference():
    variables = {"char": ["alice", "bob"]}
    for _ in range(30):
        results = expander.expand_prompts("{$char;fixed}", variables, [])
        assert results and all(r in ("alice", "bob", "fixed") for r in results)


def test_resolve_random_groups_helper_directly():
    for _ in range(30):
        assert expander._resolve_random_groups("{a;b;c}") in ("a", "b", "c")
    assert expander._resolve_random_groups("no braces here") == "no braces here"
    assert expander._resolve_random_groups("{2}") == "{2}"
