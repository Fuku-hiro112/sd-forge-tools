"""pending_jobs — Variable Manager から POST /set_jobs で送られたデータの取得・消費.

`_pending_data` は v3b.py モジュールレベルの mutable dict。
peek_jobs API から呼ばれて、取得と同時にバッファをクリアする。
"""
from __future__ import annotations

from typing import Optional


def consume_pending_jobs(pending: dict) -> Optional[dict]:
    """pending dict を消費して payload を返す。バッファはクリアする.

    Args:
        pending: モジュールレベルの _pending_data dict。in-place で書き換える。

    Returns:
        受信データがあれば {"group_list", "prompt", "negative_prompt", "timestamp"} を返し、
        pending の同名キーを None にクリアする。
        group_list が None なら受信データなしと判定し、None を返す。
    """
    if pending.get("group_list") is None:
        return None
    result = {
        "group_list": pending.get("group_list", ""),
        "prompt": pending.get("prompt"),
        "negative_prompt": pending.get("negative_prompt"),
        "timestamp": pending.get("timestamp"),
    }
    pending["group_list"] = None
    pending["prompt"] = None
    pending["negative_prompt"] = None
    pending["timestamp"] = None
    return result
