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
    effective_negative: Optional[str] = None,
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
            # 展開後ネガティブのスナップショット。再開時はこれを優先使用し、
            # 空なら現在の variables.json から再計算にフォールバックする。
            "effective_negative": effective_negative or "",
            "expansion_order": list(expansion_order),
            "used_variables": dict(used_variables),
        },
        "generation": dict(generation),
        "progress": {"completed": 0, "total": 0, "status": "running"},
    }


def build_generation_dict(p, seed_mode: str, resolved_initial_seed) -> dict:
    """p から履歴保存用の generation dict を組み立てる純関数（clip_skip 含む）.

    batch_runner / prompt_expander の両経路がこれを使い、記録内容のドリフトを防ぐ。
    """
    return {
        "width": getattr(p, "width", None),
        "height": getattr(p, "height", None),
        "cfg_scale": getattr(p, "cfg_scale", None),
        "steps": getattr(p, "steps", None),
        "sampler": getattr(p, "sampler_name", None),
        "scheduler": getattr(p, "scheduler", "Automatic"),
        "initial_seed": getattr(p, "seed", None),
        "resolved_initial_seed": resolved_initial_seed,
        "seed_mode": seed_mode,
        "clip_skip": getattr(p, "clip_skip", 1),
    }


def apply_generation_to_p(p, generation: Optional[dict]):
    """履歴の generation 設定を p に反映する（再開用）.

    width/height/cfg_scale/steps/sampler/scheduler/seed/clip_skip を復元する。
    ADetailer / Hires.fix / sd-forge-couple などの拡張設定（scripts / script_args /
    extra_generation_params / styles / hr_* / override_settings）には触れない。
    これらは履歴に保存されず、現在の UI 状態から引き継がれる前提。

    Returns:
        (seed_mode, resolved_initial_seed)
    """
    g = generation or {}
    p.width = g.get("width", getattr(p, "width", None))
    p.height = g.get("height", getattr(p, "height", None))
    p.cfg_scale = g.get("cfg_scale", getattr(p, "cfg_scale", None))
    p.steps = g.get("steps", getattr(p, "steps", None))
    p.sampler_name = g.get("sampler", getattr(p, "sampler_name", None))
    if hasattr(p, "scheduler"):
        p.scheduler = g.get("scheduler", p.scheduler)
    # clip_skip は保存されている場合のみ復元（未保存の旧エントリを壊さない）
    if "clip_skip" in g:
        p.clip_skip = g.get("clip_skip")
    seed_mode = g.get("seed_mode", "sequential")
    resolved_initial_seed = g.get(
        "resolved_initial_seed",
        g.get("initial_seed", getattr(p, "seed", None)),
    )
    p.seed = resolved_initial_seed
    return seed_mode, resolved_initial_seed


def _script_title(s) -> str:
    t = getattr(s, "title", None)
    if callable(t):
        t = t()
    return t if isinstance(t, str) else ""


def _arg_get(obj, key: str):
    """dict / dataclass 風オブジェクトのどちらからでも属性を引く."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _collect_adetailer_params(p) -> Optional[dict]:
    """p.script_args から ADetailer の検出プロンプト等をベストエフォート抽出.

    版差でキー構造が変わり得るため「記録用（参考情報）」に留め、再開復元には使わない。
    見つからない場合は None。
    """
    scripts_obj = getattr(p, "scripts", None)
    alwayson = getattr(scripts_obj, "alwayson_scripts", None) or []
    script_args = list(getattr(p, "script_args", None) or [])
    for s in alwayson:
        if "adetailer" not in _script_title(s).lower():
            continue
        a = getattr(s, "args_from", None)
        b = getattr(s, "args_to", None)
        if not isinstance(a, int) or not isinstance(b, int):
            continue
        for item in script_args[a:b]:
            model = _arg_get(item, "ad_model")
            prompt = _arg_get(item, "ad_prompt")
            if model is None and prompt is None:
                continue  # 先頭 enable フラグ等はスキップ
            return {
                "ad_model": model,
                "ad_prompt": prompt,
                "ad_negative_prompt": _arg_get(item, "ad_negative_prompt"),
            }
    return None


def collect_extension_params(p) -> dict:
    """履歴に残す「使用機能ごとのパラメータ」を p から収集する純関数.

    Hires.fix の設定と ADetailer の検出プロンプト等を best-effort で拾う。
    抽出できない拡張は静かに省略し、履歴記録自体は継続する。
    """
    out: dict = {}
    if bool(getattr(p, "enable_hr", False)):
        out["hires"] = {
            "enabled": True,
            "scale": getattr(p, "hr_scale", None),
            "upscaler": getattr(p, "hr_upscaler", None),
        }
    else:
        out["hires"] = {"enabled": False}
    ad = _collect_adetailer_params(p)
    if ad:
        out["adetailer"] = ad
    return out


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
