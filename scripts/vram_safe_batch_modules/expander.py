"""expander — メインプロンプト解析・スロット展開・変数置換.

文法:
    body  := slot*                          # スロットの直積展開
    slot  := text_slot | inline_slot
    text_slot   := alt_text                 # //.../...// 外の通常テキスト
    inline_slot := '//' alt_text '//'       # 閉じ形
                 | '//' alt_text            # 不閉じ（EOL/末尾まで）
    alt_text    := segment (';' segment)*   # ; で alternation
    segment     := (literal | var_ref)*
    var_ref     := '$' name                 # name は Unicode 単語文字

評価戦略:
    1. parse_main_prompt: 変数定義 (変数--- / 行頭 $x=...) を抽出 → body
    2. parse_body_into_slots: body を //.../...// 境界でスロット列に
    3. 各スロットを ; で分割 → alts 配列
    4. スロット alts の直積で template を生成（カンマ自動補完）
    5. 各 template の $var を再帰的に展開
       - 値が ; や // を含む場合は値を template に振り押した後、同じパーサで再評価

カンマ自動補完:
    スロット連結時、両端にカンマが無い境界に "," を1つ挿入。
    末尾の余分な "," はトリム。
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Iterable

_BLOCK_START = "変数---"
_BLOCK_END = "---"
# 変数名:
#   先頭は非数字の word 文字。続く文字は word + ( ) : 、 等を許容。
#   区切り文字（空白, =, ;, $, ASCII ,）と改行を除外する。
#   これにより `$ナンジャモ(ジム:雷)` `$アイリス(ジム:ドラゴン、四天王:BW)` などを名前として認識。
_DEF_RE = re.compile(r"^\s*\$([^\W\d][^=\s;,\$]*)\s*=\s*(.*?)\s*$", re.UNICODE)
# _VAR_RE は extract_used_variables の後方互換（辞書なし）モードでのみ使用。
# SD プロンプトの句読点（. など）で名前が止まるよう従来通り \w ベースに留める。
# 特殊文字名の検出は extract_used_variables(body, variables) の辞書駆動経路を使う。
_VAR_RE = re.compile(r"\$([^\W\d]\w*)", re.UNICODE)
_LEGACY_N_RE = re.compile(r"\{\d+\}")
_MAX_NESTED_DEPTH = 12


# ====================================================
#  ParseResult: parse_main_prompt の戻り値
# ====================================================
@dataclass
class ParseResult:
    body: str
    inline_vars: dict[str, list[str]] = field(default_factory=dict)
    has_legacy_n_notation: bool = False


def parse_main_prompt(text: str) -> ParseResult:
    """メインプロンプトから 変数--- ブロック・行頭 $x=... インライン定義を抽出.

    body は変数定義行を除去したテキスト。
    ブロック内では `$NAME=` の後に続く非定義行を値の継続として蓄積する
    （複数行に渡って `;` 区切りで値を列挙できる）。
    """
    inline_vars: dict[str, list[str]] = {}
    body_lines: list[str] = []
    in_block = False
    cur_name: str | None = None
    cur_parts: list[str] = []

    def flush_def() -> None:
        nonlocal cur_name, cur_parts
        if cur_name is not None:
            raw = "\n".join(cur_parts)
            values = _split_alternations(raw)
            if values:
                inline_vars[cur_name] = values
        cur_name = None
        cur_parts = []

    for line in text.splitlines():
        stripped = line.strip()
        if not in_block and stripped == _BLOCK_START:
            in_block = True
            continue
        if in_block and stripped == _BLOCK_END:
            flush_def()
            in_block = False
            continue

        if in_block:
            m = _DEF_RE.match(line)
            if m:
                flush_def()
                cur_name = m.group(1)
                cur_parts = [m.group(2)]
            else:
                # ブロック内の非定義行 = 現在の定義の値の継続
                if cur_name is not None:
                    cur_parts.append(line)
                # 定義開始前の継続行は無視
            continue

        # ブロック外
        m = _DEF_RE.match(line)
        if m:
            _store_definition(inline_vars, m.group(1), m.group(2))
            continue

        body_lines.append(line)

    # 閉じタグ無しでテキスト終端した場合に備えて flush
    flush_def()

    body = "\n".join(body_lines)
    has_legacy = bool(_LEGACY_N_RE.search(body))
    return ParseResult(body=body, inline_vars=inline_vars, has_legacy_n_notation=has_legacy)


def _store_definition(target: dict[str, list[str]], name: str, raw_values: str) -> None:
    values = _split_alternations(raw_values)
    if values:
        target[name] = values


def _split_alternations(text: str) -> list[str]:
    """; で区切り、各値の前後空白除去、空値はスキップ."""
    return [v.strip() for v in text.split(";") if v.strip() != ""]


def merge_variables(
    inline_vars: dict[str, list[str]],
    json_vars: dict[str, list[str]],
) -> dict[str, list[str]]:
    """インライン定義 > variables.json の優先順位でマージ."""
    merged = dict(json_vars)
    merged.update(inline_vars)
    return merged


def extract_used_variables(
    body: str,
    variables: dict[str, list[str]] | None = None,
) -> list[str]:
    """body に出現する $変数 名を出現順で重複排除して返す.

    `variables` を渡すと辞書キーとの最長一致で抽出する（特殊文字を含む名前も検出）。
    渡さない場合は正規表現ベースの抽出（後方互換）。
    """
    if variables is not None:
        return _extract_refs_with_dict(body, variables)
    seen: list[str] = []
    seen_set: set[str] = set()
    for m in _VAR_RE.finditer(body):
        name = m.group(1)
        if name not in seen_set:
            seen.append(name)
            seen_set.add(name)
    return seen


# ====================================================
#  Slot: スロット表現
# ====================================================
@dataclass
class Slot:
    kind: str  # "text" or "inline"
    alternatives: list[str]


def parse_body_into_slots(body: str) -> list[Slot]:
    """body を //.../...// 境界でスロット列に分解する.

    text スロット: 通常テキスト（;で alternation 分割）
    inline スロット: //.../...// 内（;で alternation 分割）
    不閉じの // は EOL or 本体末まで。
    """
    slots: list[Slot] = []
    i = 0
    n = len(body)
    current_text = ""

    while i < n:
        # "//" を探す
        if body[i:i+2] == "//":
            # 現在の text バッファをスロット化
            if current_text:
                slots.append(_make_text_slot(current_text))
                current_text = ""

            # // の開始位置の次から
            i += 2

            # 閉じ "//" を探す（ただし \n を越えない）
            end_in_line = body.find("\n", i)
            end_in_line = n if end_in_line == -1 else end_in_line
            close = body.find("//", i, end_in_line)

            if close == -1:
                # 不閉じ: EOL までを inline スロットに
                inline_text = body[i:end_in_line]
                slots.append(_make_inline_slot(inline_text))
                i = end_in_line
            else:
                inline_text = body[i:close]
                slots.append(_make_inline_slot(inline_text))
                i = close + 2  # 閉じ // をスキップ
        else:
            current_text += body[i]
            i += 1

    if current_text:
        slots.append(_make_text_slot(current_text))

    return slots


def _make_text_slot(text: str) -> Slot:
    alts = _split_alternations(text)
    if not alts:
        # 区切りだけ・空のテキストは空 alt を残しておく（連結時に消える）
        alts = [text]
    return Slot(kind="text", alternatives=alts)


def _make_inline_slot(text: str) -> Slot:
    alts = _split_alternations(text)
    if not alts:
        alts = [""]
    return Slot(kind="inline", alternatives=alts)


# ====================================================
#  カンマ自動補完
# ====================================================
def _join_with_auto_comma(parts: list[str]) -> str:
    """両端にカンマが無い境界に "," を挿入して連結.

    末尾の余分な "," (とそれに続く空白) は trim する。
    """
    result = ""
    for part in parts:
        if not part:
            continue
        if not result:
            result = part
            continue
        left_ends_comma = bool(re.search(r",\s*$", result))
        right_starts_comma = bool(re.match(r"^\s*,", part))
        if left_ends_comma or right_starts_comma:
            result = result + part
        else:
            result = result + "," + part
    # 末尾カンマ trim
    result = re.sub(r"\s*,\s*$", "", result)
    return result


# ====================================================
#  expand_prompts: スロット直積 + 再帰的変数展開
# ====================================================
def expand_prompts(
    body: str,
    variables: dict[str, list[str]],
    expansion_order: Iterable[str],
) -> list[str]:
    """body をスロット分解 → 直積で template 列 → 各 template に変数展開を施す."""
    order = list(expansion_order)
    slots = parse_body_into_slots(body)
    templates = _generate_templates(slots)

    results: list[str] = []
    for tpl in templates:
        results.extend(_expand_recursively(tpl, variables, order, depth=0))
    return results


def _generate_templates(slots: list[Slot]) -> list[str]:
    """スロット alts の直積から template リストを生成（カンマ自動補完つき）."""
    if not slots:
        return [""]
    alt_lists = [s.alternatives for s in slots]
    templates: list[str] = []
    for combo in itertools.product(*alt_lists):
        templates.append(_join_with_auto_comma(list(combo)))
    return templates


def _find_var_ref_at(
    text: str,
    pos: int,
    variables: dict[str, list[str]],
) -> str | None:
    """text[pos]=='$' の位置で variables のキーから最長一致を返す.

    名前が word 文字で終わる場合、続きが word なら一致させない（境界チェック）。
    非 word 終端の名前（例: "foo(bar)"）は境界チェック不要。
    """
    if pos >= len(text) or text[pos] != "$":
        return None
    best: str | None = None
    after_pos = pos + 1
    for name in variables:
        if not name:
            continue
        if not text.startswith(name, after_pos):
            continue
        end = after_pos + len(name)
        last = name[-1]
        if last.isalnum() or last == "_":
            if end < len(text):
                nxt = text[end]
                if nxt.isalnum() or nxt == "_":
                    continue
        if best is None or len(name) > len(best):
            best = name
    return best


def _extract_refs_with_dict(
    text: str,
    variables: dict[str, list[str]],
) -> list[str]:
    """variables のキーを最長一致で text から検出。出現順・重複排除."""
    refs: list[str] = []
    seen: set[str] = set()
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "$":
            name = _find_var_ref_at(text, i, variables)
            if name:
                if name not in seen:
                    refs.append(name)
                    seen.add(name)
                i += 1 + len(name)
                continue
        i += 1
    return refs


def _expand_recursively(
    template: str,
    variables: dict[str, list[str]],
    order: list[str],
    depth: int,
) -> list[str]:
    """template に残る $var を再帰的に展開する.

    - order を優先（外側ループ）
    - order に無い変数は出現順で自動追加（内側ループ）
    - 値が ; や // を含む場合は値を template に挿入後、再度 slot parser を通す
    """
    if depth > _MAX_NESTED_DEPTH:
        return [template]

    refs = _extract_refs_with_dict(template, variables)
    if not refs:
        # 末尾カンマトリムだけして返す（再評価で残るケース対策）
        return [re.sub(r"\s*,\s*$", "", template)]

    # 次に展開する変数を決定
    next_var = None
    for name in order:
        if name in refs and name in variables:
            next_var = name
            break
    if next_var is None:
        for name in refs:
            if name in variables:
                next_var = name
                break

    if next_var is None:
        # 残る $var は全て未定義 → リテラルとして残す
        return [re.sub(r"\s*,\s*$", "", template)]

    new_order = [n for n in order if n != next_var]
    values = variables[next_var]

    # iteration: 値を一つ当てて新 template を作る → 値が ;// を含むなら再 slot 解析
    results: list[str] = []
    for value in values:
        # 1 回だけ next_var を value で置換
        substituted = _substitute_var(template, next_var, value)
        # 値内の ;// を再評価
        sub_slots = parse_body_into_slots(substituted)
        sub_templates = _generate_templates(sub_slots)
        for st in sub_templates:
            results.extend(_expand_recursively(st, variables, new_order, depth + 1))
    return results


def _substitute_var(text: str, name: str, value: str) -> str:
    """text 中の $name を value で全置換."""
    pattern = re.compile(r"\$" + re.escape(name) + r"(?![\w])", re.UNICODE)
    return pattern.sub(lambda _m: value, text)


# ====================================================
#  Phase C: ネガティブプロンプト自動流入
# ====================================================
def collect_negative_additions(
    body: str,
    variables: dict[str, list[str]],
    negative_dict: dict[str, list[str]],
) -> list[str]:
    """body に直接出現する変数名から negative 値を出現順・重複排除で集める.

    Args:
        body: 変数定義ブロック除去後のメインプロンプト本体
        variables: positive 値の flat dict（辞書駆動の変数抽出に使用）
        negative_dict: negative 値の flat dict

    Returns:
        負プロンプトに追加すべき値のリスト（空文字列除外、出現順）
    """
    used = extract_used_variables(body, variables)
    out: list[str] = []
    seen: set[str] = set()
    for name in used:
        for val in negative_dict.get(name, []):
            if val and val not in seen:
                out.append(val)
                seen.add(val)
    return out


def compose_negative_prompt(original, additions: list[str]) -> str:
    """original のネガティブと additions をカンマ区切りで結合する.

    - None や空文字列の original は空扱い
    - additions のうち、original 内のトークン（,split + strip 比較）と重複するものはスキップ
    - additions 内部の重複も除外（出現順は維持）
    - original 末尾の余分なカンマ・空白はトリム
    """
    orig = (original or "").strip().rstrip(",").rstrip()
    original_tokens: set[str] = set()
    for t in (original or "").split(","):
        s = t.strip()
        if s:
            original_tokens.add(s)

    parts: list[str] = []
    if orig:
        parts.append(orig)

    for val in additions or []:
        s = val.strip() if isinstance(val, str) else ""
        if not s or s in original_tokens:
            continue
        parts.append(s)
        original_tokens.add(s)

    return ", ".join(parts)
