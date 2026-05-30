"""
text_tools.py - 置換ツール・カラープレビュー生成モジュール

【機能】
1. テキスト置換（正規表現・大文字小文字対応）
2. カラープレビュー生成（コメント・変数・区切り・枚数指定を色分け）
"""

import re


# ==========================================
#  置換ツール
# ==========================================

def _build_pattern(search, use_regex, case_sensitive):
    """検索パターンを構築する。失敗時はNoneを返す"""
    if not search:
        return None
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        if use_regex:
            pattern = re.compile(search, flags)
        else:
            pattern = re.compile(re.escape(search), flags)
        return pattern
    except re.error:
        return None


def find_matches(text, search, use_regex, case_sensitive):
    """全マッチ箇所の(start, end)リストを返す"""
    pattern = _build_pattern(search, use_regex, case_sensitive)
    if not pattern or not text:
        return []
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


def get_match_info(text, search, use_regex, case_sensitive, match_index):
    """マッチ情報テキストを返す（N/M件目 + 前後の抜粋）

    Returns:
        (info_text, valid_index)
        info_text: 表示用文字列
        valid_index: 有効なmatch_index（範囲外の場合は補正済み）
    """
    matches = find_matches(text, search, use_regex, case_sensitive)

    if not matches:
        return "マッチなし", 0

    # インデックスを有効範囲に補正
    total = len(matches)
    idx = max(0, min(match_index, total - 1))

    start, end = matches[idx]

    # 前後の抜粋（最大20文字）
    context_before = text[max(0, start - 20):start]
    matched_text = text[start:end]
    context_after = text[end:min(len(text), end + 20)]

    # 改行は表示用に置換
    context_before = context_before.replace("\n", "↵")
    matched_text = matched_text.replace("\n", "↵")
    context_after = context_after.replace("\n", "↵")

    info = f"{idx + 1}/{total}件目: ...{context_before}【{matched_text}】{context_after}..."
    return info, idx


def replace_one(text, search, replace, use_regex, case_sensitive, match_index):
    """指定インデックスのマッチを1件置換する

    Returns:
        (updated_text, info_text, new_index)
    """
    matches = find_matches(text, search, use_regex, case_sensitive)

    if not matches:
        return text, "マッチなし", 0

    total = len(matches)
    idx = max(0, min(match_index, total - 1))
    start, end = matches[idx]

    pattern = _build_pattern(search, use_regex, case_sensitive)

    # 対象箇所のみ置換
    try:
        if use_regex:
            # 正規表現の場合はグループ参照を処理するためsubを使う
            prefix = text[:start]
            suffix = text[end:]
            matched_part = text[start:end]
            replaced_part = pattern.sub(replace, matched_part, count=1)
            new_text = prefix + replaced_part + suffix
        else:
            new_text = text[:start] + replace + text[end:]
    except re.error as e:
        return text, f"置換エラー: {e}", idx

    # 置換後の新しいマッチ情報を取得
    new_matches = find_matches(new_text, search, use_regex, case_sensitive)
    new_total = len(new_matches)

    if new_total == 0:
        return new_text, "マッチなし（置換完了）", 0

    new_idx = min(idx, new_total - 1)
    info, valid_idx = get_match_info(new_text, search, use_regex, case_sensitive, new_idx)
    return new_text, info, valid_idx


def replace_all(text, search, replace, use_regex, case_sensitive):
    """全マッチを一括置換する

    Returns:
        (updated_text, info_text)
    """
    pattern = _build_pattern(search, use_regex, case_sensitive)

    if not pattern or not text:
        return text, "マッチなし"

    matches = find_matches(text, search, use_regex, case_sensitive)
    count = len(matches)

    if count == 0:
        return text, "マッチなし"

    try:
        new_text = pattern.sub(replace, text)
    except re.error as e:
        return text, f"置換エラー: {e}"

    return new_text, f"{count}件を置換しました"


def navigate_match(text, search, use_regex, case_sensitive, match_index, direction):
    """マッチ箇所を前後に移動する

    Args:
        direction: 1=次へ, -1=前へ

    Returns:
        (info_text, new_index)
    """
    matches = find_matches(text, search, use_regex, case_sensitive)

    if not matches:
        return "マッチなし", 0

    total = len(matches)
    # 循環するインデックス
    new_idx = (match_index + direction) % total
    info, valid_idx = get_match_info(text, search, use_regex, case_sensitive, new_idx)
    return info, valid_idx


# ==========================================
#  カラープレビュー生成
# ==========================================

# カラーテーマ
COLORS = {
    "background": "#1e1e2e",
    "text": "#cdd6f4",
    "comment": "#6c7086",       # グレー: ## コメント
    "variable": "#89b4fa",      # 青: $変数名
    "separator": "#fab387",     # オレンジ: // と ;
    "divider": "#a6adc8",       # グレー: ---
    "count": "#a6e3a1",         # 緑: |数字
    "equals": "#f38ba8",        # 赤: =
}


def _escape_html(text):
    """HTMLエスケープ"""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _colorize_line(line):
    """1行をカラー付きHTMLに変換する（変数定義エリア・生成リストエリア共通）"""

    # --- 区切り線
    if line.strip() == "---":
        return (
            f'<div style="border-top: 1px solid {COLORS["divider"]}; '
            f'color: {COLORS["divider"]}; text-align: center; '
            f'margin: 4px 0; padding: 2px 0;">--- 変数定義ここまで ---</div>'
        )

    # ## コメントの処理（行中に ## がある場合）
    comment_html = ""
    main_part = line
    if "##" in line:
        idx = line.index("##")
        main_part = line[:idx]
        comment_text = line[idx:]
        comment_html = (
            f'<span style="color: {COLORS["comment"]};">'
            f'{_escape_html(comment_text)}</span>'
        )

    # main_partをトークンに分解してカラー付けする
    result = _colorize_main(main_part)
    return result + comment_html


def _colorize_main(text):
    """メインテキスト部分をカラー付けする

    処理対象:
    - $変数名 → 青
    - // → オレンジ
    - ; → オレンジ
    - |数字 → 緑
    - = (変数定義の=) → 赤
    - その他 → 通常色
    """
    if not text:
        return ""

    # トークナイズ用の正規表現
    # 優先順位順に定義
    token_pattern = re.compile(
        r'(\$[^\s=;|/]+)'      # $変数名
        r'|(\|\d+)'             # |数字
        r'|(//)+'              # //
        r'|(;)'                 # ;
        r'|( = )'               # = (スペース付き)
    )

    result = ""
    last_end = 0

    for m in token_pattern.finditer(text):
        # マッチ前の通常テキスト
        if m.start() > last_end:
            result += f'<span style="color: {COLORS["text"]};">{_escape_html(text[last_end:m.start()])}</span>'

        matched = m.group(0)

        if m.group(1):  # $変数名
            result += f'<span style="color: {COLORS["variable"]};">{_escape_html(matched)}</span>'
        elif m.group(2):  # |数字
            result += f'<span style="color: {COLORS["count"]};">{_escape_html(matched)}</span>'
        elif m.group(3):  # //
            result += f'<span style="color: {COLORS["separator"]};">{_escape_html(matched)}</span>'
        elif m.group(4):  # ;
            result += f'<span style="color: {COLORS["separator"]};">{_escape_html(matched)}</span>'
        elif m.group(5):  # =
            result += f'<span style="color: {COLORS["equals"]};">{_escape_html(matched)}</span>'

        last_end = m.end()

    # 残りの通常テキスト
    if last_end < len(text):
        result += f'<span style="color: {COLORS["text"]};">{_escape_html(text[last_end:])}</span>'

    return result


def generate_preview_html(text):
    """テキスト全体をカラー付きHTMLに変換する"""
    if not text or not text.strip():
        return (
            f'<div style="font-family: monospace; background: {COLORS["background"]}; '
            f'padding: 12px; border-radius: 6px; color: {COLORS["comment"]}; '
            f'font-size: 13px;">'
            f'（生成リストを入力するとここにプレビューが表示されます）'
            f'</div>'
        )

    lines = text.split("\n")
    html_lines = []

    for line in lines:
        colored = _colorize_line(line)
        html_lines.append(
            f'<div style="min-height: 1.4em; padding: 1px 0;">{colored}</div>'
        )

    inner = "\n".join(html_lines)
    return (
        f'<div style="font-family: \'Consolas\', \'Monaco\', monospace; '
        f'background: {COLORS["background"]}; '
        f'padding: 12px 16px; border-radius: 6px; '
        f'font-size: 13px; line-height: 1.6; '
        f'white-space: pre-wrap; word-break: break-all; '
        f'border: 1px solid #313244; overflow-x: auto;">'
        f'{inner}'
        f'</div>'
    )
