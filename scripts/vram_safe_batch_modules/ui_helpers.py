"""
ui_helpers.py - UI ユーティリティ関数群

vram_safe_batch_v3b.py から抽出した、履歴ドロップダウン・
DataFrame 正規化・展開プレビュー計算などの UI ヘルパー関数。
"""

import os

from . import history_v2, expander, variables_store


def _history_choices(base_dir: str) -> list[str]:
    """ドロップダウン用の選択肢リスト."""
    entries = history_v2.load_history(base_dir)
    if not entries:
        return ["履歴なし"]
    choices = []
    for i, entry in enumerate(entries):
        ts = entry.get("timestamp", "?")
        progress = entry.get("progress", {})
        completed = progress.get("completed", 0)
        total = progress.get("total", 0)
        status = progress.get("status", "?")
        main = entry.get("prompt", {}).get("main", "")[:40]
        choices.append(f"{i+1}. [{status}] {completed}/{total} {ts} | {main}")
    return choices


def _entry_detail(base_dir: str, idx: int) -> str:
    """履歴詳細テキスト."""
    entries = history_v2.load_history(base_dir)
    if not entries or idx < 0 or idx >= len(entries):
        return ""
    e = entries[idx]
    p = e.get("prompt", {})
    g = e.get("generation", {})
    pr = e.get("progress", {})
    return (
        f"ID: {e.get('id', '?')}\n"
        f"日時: {e.get('timestamp', '?')}\n"
        f"状態: {pr.get('status', '?')} ({pr.get('completed', 0)}/{pr.get('total', 0)})\n"
        f"展開順: {p.get('expansion_order', [])}\n"
        f"プロンプト: {p.get('main', '')[:100]}\n"
        f"画像: {g.get('width', '?')}x{g.get('height', '?')}, "
        f"steps={g.get('steps', '?')}, seed={g.get('initial_seed', '?')}"
    )


def _parse_dropdown_index(choice: str) -> int:
    if not choice or choice == "履歴なし":
        return -1
    try:
        return int(choice.split(".")[0]) - 1
    except Exception:
        return -1


def _normalize_df(data) -> list[list[str]]:
    """Dataframe の value を list[list[str]] に正規化.

    Gradio は type='array' でも pandas.DataFrame を返してくることがあるため両対応。
    空文字列の行・None の行は除外する。
    """
    if data is None:
        return []
    # pandas.DataFrame の場合
    try:
        import pandas as pd
        if isinstance(data, pd.DataFrame):
            data = data.values.tolist()
    except ImportError:
        pass
    result: list[list[str]] = []
    for row in data:
        if row is None:
            continue
        if not isinstance(row, (list, tuple)):
            row = [row]
        cells = []
        for cell in row:
            if cell is None:
                cells.append("")
            else:
                cells.append(str(cell).strip())
        if cells and cells[0]:
            result.append(cells)
    return result


def _compute_expansion_preview(main_prompt: str, expansion_order_text: str, base_dir: str) -> str:
    """生成枚数プレビューを計算."""
    if not main_prompt:
        return "メインプロンプトを入力してください"
    try:
        parsed = expander.parse_main_prompt(main_prompt)
        json_vars = variables_store.load_variables(os.path.join(base_dir, "vars", "variables.json"))
        merged = expander.merge_variables(parsed.inline_vars, json_vars)
        order = [s.strip() for s in expansion_order_text.splitlines() if s.strip()]
        if not order:
            used = expander.extract_used_variables(parsed.body, merged)
            order = [v for v in used if v in merged]
        expanded = expander.expand_prompts(parsed.body, merged, order)
        n = len(expanded)
        msg = f"🔢 {n} 枚生成される予定"
        if parsed.has_legacy_n_notation:
            msg += "  ⚠ 旧 {N} 記法を検出（廃止予定、$変数 に書き換えてください）"
        return msg
    except Exception as e:
        return f"⚠ 解析エラー: {e}"
