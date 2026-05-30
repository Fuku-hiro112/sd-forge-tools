"""history_v2 — batch_history.json schema v2 の読み書き.

schema v2:
{
  "schema_version": 2,
  "entries": [
    {
      "id": "20260520-091533-a1b2",
      "timestamp": "2026-05-20 09:15:33",
      "extensions": {"vram_safe_batch": "3b.2.0"},
      "prompt": {"main": "...", "negative": "...",
                 "expansion_order": [...], "used_variables": {...}},
      "generation": {...},
      "progress": {"completed": N, "total": M, "status": "running|completed|interrupted"}
    }
  ]
}

旧 schema は migrate_legacy_if_needed() で .bak.<ts> にリネームして破棄。
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime
from typing import Optional

SCHEMA_VERSION = 2
HISTORY_FILENAME = "batch_history.json"
VRAM_SAFE_BATCH_VERSION = "3b.2.0"
DEFAULT_MAX_ENTRIES = 5


def _history_path(base_dir: str) -> str:
    return os.path.normpath(os.path.join(base_dir, HISTORY_FILENAME))


def load_history(base_dir: str) -> list[dict]:
    path = _history_path(base_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[history_v2] failed to load {path}: {e}")
        return []

    if not isinstance(data, dict):
        return []
    if data.get("schema_version") != SCHEMA_VERSION:
        return []
    entries = data.get("entries")
    if not isinstance(entries, list):
        return []
    return entries


def save_history(base_dir: str, entries: list[dict]) -> None:
    path = _history_path(base_dir)
    payload = {"schema_version": SCHEMA_VERSION, "entries": list(entries)}
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError as e:
        print(f"[history_v2] failed to save {path}: {e}")


def migrate_legacy_if_needed(base_dir: str) -> Optional[str]:
    """旧スキーマの batch_history.json を検出したら .bak.<ts> にリネーム.

    Returns:
        リネーム後の絶対パス。何もしなかった場合は None。
    """
    path = _history_path(base_dir)
    if not os.path.isfile(path):
        return None

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        # 破損ファイルも安全のためリネーム
        data = None

    is_v2 = (
        isinstance(data, dict)
        and data.get("schema_version") == SCHEMA_VERSION
    )
    if is_v2:
        return None

    ts = time.strftime("%Y%m%d-%H%M%S")
    bak_path = f"{path}.bak.{ts}"
    # 競合した場合は連番を付ける
    counter = 1
    while os.path.exists(bak_path):
        bak_path = f"{path}.bak.{ts}-{counter}"
        counter += 1
    os.rename(path, bak_path)
    print(f"[history_v2] migrated legacy history → {bak_path}")
    return bak_path


def create_entry(
    prompt_main: str,
    prompt_negative: str,
    expansion_order: list[str],
    used_variables: dict[str, list[str]],
    generation: dict,
    extensions: Optional[dict] = None,
) -> dict:
    now = datetime.now()
    eid = now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    return {
        "id": eid,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "extensions": extensions or {"vram_safe_batch": VRAM_SAFE_BATCH_VERSION},
        "prompt": {
            "main": prompt_main,
            "negative": prompt_negative,
            "expansion_order": list(expansion_order),
            "used_variables": dict(used_variables),
        },
        "generation": dict(generation),
        "progress": {"completed": 0, "total": 0, "status": "running"},
    }


def add_entry(base_dir: str, entry: dict, max_entries: int = DEFAULT_MAX_ENTRIES) -> list[dict]:
    entries = load_history(base_dir)
    entries.insert(0, entry)
    if max_entries > 0:
        entries = entries[:max_entries]
    save_history(base_dir, entries)
    return entries


def update_entry(base_dir: str, entry_id: str, **updates) -> bool:
    entries = load_history(base_dir)
    for i, entry in enumerate(entries):
        if entry.get("id") == entry_id:
            entries[i] = {**entry, **updates}
            save_history(base_dir, entries)
            return True
    return False


def get_entry(base_dir: str, entry_id: str) -> Optional[dict]:
    for entry in load_history(base_dir):
        if entry.get("id") == entry_id:
            return entry
    return None
