"""
progress.py - 進捗・履歴管理モジュール

履歴を最大5件保持し、ドロップダウンで選択・再開できます。
"""

import os
import json
import secrets
from datetime import datetime

# 履歴ファイルパス（WebUIルートフォルダに配置）
HISTORY_FILE = None
MAX_HISTORY = 5


# ============================================================
#  §2 シード値モード（固定 / 連番）
# ============================================================

def compute_seed(mode: str, initial_seed: int, global_num: int) -> int:
    """シードモードに応じて global_num 番目（1-origin）のシード値を返す純粋関数.

    Args:
        mode: "fixed" または "sequential"
        initial_seed: 解決済み初期シード（-1 は禁止。resolve_initial_seed() で解決してから渡す）
        global_num: 1 から始まる通し番号

    Returns:
        その画像に使うシード値
    """
    if initial_seed is None or initial_seed < 0:
        raise ValueError(
            f"compute_seed: initial_seed must be resolved (>=0), got {initial_seed!r}"
        )
    if mode == "fixed":
        return initial_seed
    if mode == "sequential":
        return initial_seed + (global_num - 1)
    raise ValueError(f"compute_seed: unknown mode {mode!r}")


def should_update_completed(success: bool, is_interrupted: bool) -> bool:
    """§3: completed カウンタを進めて良いかを返す純粋関数.

    中断時 (is_interrupted=True) は、`generate_one()` が部分結果と共に成功扱いを返してきても
    バンプしない。これにより resume 時に同じ画像番号から再生成される（歯抜け回避）。

    Args:
        success: generate_one() が成功扱いを返したか
        is_interrupted: 中断フラグ

    Returns:
        True なら last_confirmed_num をバンプして history を更新して良い
    """
    return bool(success) and not bool(is_interrupted)


def compute_focus_update(current_value, new_choices):
    """§4: ドロップダウンを focus した瞬間の choices / value を計算する純粋関数.

    Args:
        current_value: 現在のドロップダウン値（None 可）
        new_choices: 再計算後の choices リスト

    Returns:
        (choices, value): 新しい choices と維持/フォールバック後の value。
        new_choices が空なら ([], None)。
        current_value が new_choices に含まれていればそれを維持、
        含まれていなければ先頭を返す。
    """
    choices = list(new_choices)
    if not choices:
        return [], None
    if current_value in choices:
        return choices, current_value
    return choices, choices[0]


def resolve_initial_seed(initial_seed) -> int:
    """-1 / None のとき WebUI と同様に乱択して非負整数を返す.

    解決済みの非負整数はそのまま返す。
    """
    if initial_seed is None:
        return secrets.randbelow(2**32 - 1)
    try:
        value = int(initial_seed)
    except (TypeError, ValueError):
        return secrets.randbelow(2**32 - 1)
    if value < 0:
        return secrets.randbelow(2**32 - 1)
    return value


def _get_history_path(base_dir):
    return os.path.normpath(os.path.join(base_dir, "batch_history.json"))


def load_history(base_dir):
    """履歴ファイルを読み込む。なければ空リストを返す"""
    path = _get_history_path(base_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history(base_dir, history):
    """履歴ファイルを保存する"""
    path = _get_history_path(base_dir)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠ 履歴保存エラー: {e}")


def add_history_entry(base_dir, progress_data):
    """新しい進捗エントリを履歴に追加（最大5件、古いものを削除）"""
    history = load_history(base_dir)

    # タイムスタンプを追加
    progress_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 先頭に追加
    history.insert(0, progress_data)

    # 最大5件に制限
    history = history[:MAX_HISTORY]

    save_history(base_dir, history)
    return history


def update_history_entry(base_dir, index, progress_data):
    """指定インデックスの履歴エントリを更新"""
    history = load_history(base_dir)
    if 0 <= index < len(history):
        # タイムスタンプは変更しない
        ts = history[index].get("timestamp", "")
        history[index] = progress_data
        history[index]["timestamp"] = ts
        save_history(base_dir, history)


def get_resumable_entries(base_dir):
    """再開可能な履歴エントリのリストを返す（全履歴、完了済みも含む）"""
    history = load_history(base_dir)
    return history


def get_dropdown_choices(base_dir):
    """ドロップダウン用の選択肢リストを返す"""
    history = load_history(base_dir)
    choices = []

    for i, entry in enumerate(history):
        ts = entry.get("timestamp", "不明")
        completed = entry.get("completed", 0)
        total = entry.get("total", 0)
        status = entry.get("status", "unknown")

        if total > 0:
            pct = int(completed / total * 100)
        else:
            pct = 0

        # リストの内容を短く表示
        slots = entry.get("slots", [])
        slot_summary = " × ".join(
            ", ".join(s[:2]) + ("..." if len(s) > 2 else "")
            for s in slots[:3]
        )

        if status == "completed":
            status_str = "完了"
        elif status == "running":
            status_str = f"{completed}/{total}枚 ({pct}%)"
        else:
            status_str = "不明"

        label = f"{i+1}. {ts} | {status_str} | {slot_summary}"
        choices.append(label)

    if not choices:
        choices = ["履歴なし"]

    return choices


def get_entry_detail(base_dir, index):
    """指定インデックスの履歴エントリの詳細テキストを返す"""
    history = load_history(base_dir)
    if not history or index < 0 or index >= len(history):
        return "履歴がありません"

    entry = history[index]
    ts = entry.get("timestamp", "不明")
    completed = entry.get("completed", 0)
    total = entry.get("total", 0)
    status = entry.get("status", "unknown")
    prompt = entry.get("prompt", "")
    slots = entry.get("slots", [])

    if total > 0:
        pct = int(completed / total * 100)
    else:
        pct = 0

    status_str = "完了" if status == "completed" else f"{completed}/{total}枚 ({pct}%)"

    lines = [
        f"日時: {ts}",
        f"進捗: {status_str}",
        f"プロンプト: {prompt[:80]}{'...' if len(prompt) > 80 else ''}",
    ]

    for i, slot in enumerate(slots):
        slot_str = " / ".join(slot[:5])
        if len(slot) > 5:
            slot_str += f" ...他{len(slot)-5}件"
        lines.append(f"リスト{i+1}: {slot_str}")

    return "\n".join(lines)


def create_new_progress(base_dir, prompt, negative_prompt, width, height,
                        cfg_scale, steps, sampler, scheduler, seed,
                        clip_skip, default_count, slots, slot_counts,
                        active_indices, total):
    """新しい進捗データを作成して履歴に追加し、インデックスを返す"""
    progress_data = {
        "status": "running",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "cfg_scale": cfg_scale,
        "steps": steps,
        "sampler": sampler,
        "scheduler": scheduler,
        "seed": seed,
        "clip_skip": clip_skip,
        "default_count": default_count,
        "slots": slots,
        "slot_counts": slot_counts,
        "active_indices": active_indices,
        "completed": 0,
        "total": total,
    }

    history = add_history_entry(base_dir, progress_data)
    return 0  # 先頭に追加されるので常にindex=0


def update_completed(base_dir, history_index, completed_num):
    """指定履歴の完了枚数を更新"""
    history = load_history(base_dir)
    if 0 <= history_index < len(history):
        history[history_index]["completed"] = completed_num
        save_history(base_dir, history)


def mark_completed(base_dir, history_index):
    """指定履歴をcompletedにマーク"""
    history = load_history(base_dir)
    if 0 <= history_index < len(history):
        history[history_index]["status"] = "completed"
        save_history(base_dir, history)


def get_entry(base_dir, history_index):
    """指定インデックスの履歴エントリを返す"""
    history = load_history(base_dir)
    if 0 <= history_index < len(history):
        return history[history_index]
    return None


def is_resumable(base_dir, history_index):
    """指定履歴が再開可能かどうかを返す"""
    entry = get_entry(base_dir, history_index)
    if not entry:
        return False
    return (entry.get("status") == "running" and
            entry.get("completed", 0) < entry.get("total", 0))
