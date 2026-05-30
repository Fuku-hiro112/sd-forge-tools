"""variables_store — vars/variables.json の読み書き.

Schema:
    v1 (legacy):
        {"schema_version": 1,
         "variables": [{"name": "char", "category": "...", "values": [...]}, ...]}

    v2 (Variable Manager と同形式 / Phase A 同期):
        {"schema_version": 2,
         "categories": [
            {"name": "characters",
             "children": [{"name": "pokemon",
                            "children": [],
                            "variables": [{"name": "nanjamo",
                                            "positive": "iono",
                                            "negative": ""}]
                          }],
             "variables": []}]}

`load_variables` は破損や非対応スキーマの場合に空 dict を返し、呼び出し側を守る。
v1 / v2 どちらでもロードでき、内部表現は flat `{var_name: [positive_value]}` を返す
（既存 expander の API 不変）。

`save_variables` は v1 schema で書き出す（後方互換）。
`save_variables_v2` は v2 ツリー構造をそのまま書き出し、既存ファイルがあれば
`.bak.{timestamp}` に自動退避する。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

# v1 は legacy schema、v2 は Variable Manager 同期で使用
SCHEMA_VERSION = 1            # save_variables 既定（後方互換）
SCHEMA_VERSION_V2 = 2


def load_variables(vars_path: str) -> dict[str, list[str]]:
    """v1 / v2 どちらの schema でも flat `{name: [positive_value]}` を返す."""
    if not os.path.isfile(vars_path):
        return {}
    try:
        with open(vars_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[variables_store] failed to load {vars_path}: {e}")
        return {}

    if not isinstance(data, dict):
        return {}

    ver = data.get("schema_version")
    if ver == SCHEMA_VERSION:
        return _load_v1_flat(data)
    if ver == SCHEMA_VERSION_V2:
        return _load_v2_positive_flat(data)

    print(f"[variables_store] unsupported schema in {vars_path}: {ver!r}")
    return {}


def _load_v1_flat(data: dict) -> dict[str, list[str]]:
    entries = data.get("variables")
    if not isinstance(entries, list):
        return {}
    result: dict[str, list[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        values = entry.get("values")
        if not isinstance(name, str) or not isinstance(values, list):
            continue
        result[name] = [str(v) for v in values]
    return result


def _strip_dollar_prefix(name: str) -> str:
    """Variable Manager は name に "$" を含めて保存するが、expander 側は "$" 抜きで照合する.

    変換は冪等で、`$` で始まらない名前はそのまま返す。
    """
    if isinstance(name, str) and name.startswith("$"):
        return name[1:]
    return name


def _normalize_value(s) -> str:
    """値の前後の空白と "; " を除去する（Variable Manager の値スタイル吸収）.

    Manager 慣習で値末尾に ";" が付く場合があるが、これが残ると substitute 後の
    本文と連結したとき spurious な alt 境界を作る。前後の空白・";" を除去して、
    内部の ";" は alternation 区切りとして保持する。
    """
    if not isinstance(s, str):
        return ""
    return s.strip().strip(";").strip()


def _load_v2_positive_flat(data: dict) -> dict[str, list[str]]:
    """v2 ツリーから positive 値だけを flat dict 化して返す."""
    categories = data.get("categories")
    if not isinstance(categories, list):
        return {}
    result: dict[str, list[str]] = {}
    for var in walk_variables(categories):
        name = _strip_dollar_prefix(var.get("name"))
        positive = _normalize_value(var.get("positive", ""))
        if not isinstance(name, str) or not name or not positive:
            continue
        result[name] = [positive]
    return result


def load_negative_dict(vars_path: str) -> dict[str, list[str]]:
    """v2 ツリーから negative 値だけを flat dict 化して返す（v2 のみ対応）.

    将来 v3b のネガティブプロンプト流入で使用予定。
    """
    if not os.path.isfile(vars_path):
        return {}
    try:
        with open(vars_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION_V2:
        return {}
    categories = data.get("categories")
    if not isinstance(categories, list):
        return {}
    result: dict[str, list[str]] = {}
    for var in walk_variables(categories):
        name = _strip_dollar_prefix(var.get("name"))
        negative = _normalize_value(var.get("negative", ""))
        if not isinstance(name, str) or not name or not negative:
            continue
        result[name] = [negative]
    return result


def load_raw_v2(vars_path: str) -> dict:
    """v2 の生 JSON（ツリー構造のまま）を返す。GET /variables 用.

    ファイルが無い・破損・非 v2 スキーマの場合は空 v2 スケルトンを返す。
    """
    empty = {"schema_version": SCHEMA_VERSION_V2, "categories": []}
    if not os.path.isfile(vars_path):
        return empty
    try:
        with open(vars_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION_V2:
        return empty
    return data


def walk_variables(categories: list) -> Iterator[dict]:
    """カテゴリツリーを再帰的に walk し、全変数を yield する純粋関数.

    各 yield には category_path: list[str] を付与（親→子の順）。
    """
    def _walk(nodes, path):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            cname = node.get("name")
            current_path = path + ([cname] if isinstance(cname, str) else [])
            for var in (node.get("variables") or []):
                if isinstance(var, dict):
                    yield {**var, "category_path": current_path}
            yield from _walk(node.get("children") or [], current_path)
    yield from _walk(categories or [], [])


def save_variables(
    vars_path: str,
    variables: dict[str, list[str]],
    categories: Optional[dict[str, str]] = None,
) -> None:
    """v1 schema で flat dict を書き出す（後方互換 API）."""
    parent = os.path.dirname(os.path.abspath(vars_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    entries = []
    for name, values in variables.items():
        entry: dict = {"name": name, "values": list(values)}
        if categories and name in categories:
            entry["category"] = categories[name]
        entries.append(entry)

    payload = {"schema_version": SCHEMA_VERSION, "variables": entries}
    tmp_path = vars_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, vars_path)


def _utc_now_iso() -> str:
    """ISO8601 UTC タイムスタンプ（秒精度 + Z 表記）."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp_missing_updated_at(categories: list, now: Optional[str] = None) -> list:
    """ツリーを in-place で変更しないように deep-copy しつつ updated_at 未設定の変数に現在時刻を付与."""
    ts = now or _utc_now_iso()
    def _stamp(nodes):
        out = []
        for node in nodes:
            if not isinstance(node, dict):
                out.append(node)
                continue
            new_vars = []
            for v in (node.get("variables") or []):
                if isinstance(v, dict) and "updated_at" not in v:
                    new_vars.append({**v, "updated_at": ts})
                else:
                    new_vars.append(v)
            new_children = _stamp(node.get("children") or [])
            out.append({**node, "variables": new_vars, "children": new_children})
        return out
    return _stamp(categories or [])


def save_variables_v2(vars_path: str, categories_tree: list) -> Optional[str]:
    """v2 ツリー構造をそのまま書き出し。既存ファイルがあれば .bak.{ts} に自動退避.

    updated_at が無い変数には保存時に現在時刻を自動付与する（Phase B last-write-wins 用）。

    Returns:
        作成した .bak ファイルの絶対パス、ファイルが無く退避不要だった場合は None。
    """
    parent = os.path.dirname(os.path.abspath(vars_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    bak_path = None
    if os.path.isfile(vars_path):
        bak_path = _backup_path(vars_path)
        try:
            os.replace(vars_path, bak_path)
        except OSError as e:
            print(f"[variables_store] backup failed for {vars_path}: {e}")
            bak_path = None

    stamped = _stamp_missing_updated_at(list(categories_tree))
    payload = {"schema_version": SCHEMA_VERSION_V2, "categories": stamped}
    tmp_path = vars_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, vars_path)
    return bak_path


# ============================================================
#  Phase B: 変数ごと updated_at で last-write-wins マージ
# ============================================================

def merge_by_updated_at(local: list, remote: list) -> list:
    """ローカル / リモートのカテゴリツリーを変数名キーで last-write-wins マージ.

    - 各変数の `updated_at` を比較し、新しい方を採用
    - `updated_at` 未設定の変数は最古として扱う
    - カテゴリ構造（name / children の階層）は local を優先するが、remote にしかない
      カテゴリ・変数は追加する
    - 戻り値は新しい dict ツリー（引数は変更しない）
    """
    return _merge_nodes(local or [], remote or [])


def _merge_nodes(local_nodes: list, remote_nodes: list) -> list:
    """カテゴリ list 同士を name キーでマージ."""
    by_name_local = {n.get("name"): n for n in local_nodes if isinstance(n, dict)}
    by_name_remote = {n.get("name"): n for n in remote_nodes if isinstance(n, dict)}
    merged: list = []
    seen: set = set()
    # local の順序を尊重しつつマージ
    for lnode in local_nodes:
        if not isinstance(lnode, dict):
            continue
        name = lnode.get("name")
        seen.add(name)
        rnode = by_name_remote.get(name)
        if rnode is None:
            merged.append(_deep_copy_node(lnode))
        else:
            merged.append(_merge_one_node(lnode, rnode))
    # remote にしかないカテゴリを末尾に追加
    for rnode in remote_nodes:
        if not isinstance(rnode, dict):
            continue
        name = rnode.get("name")
        if name in seen:
            continue
        merged.append(_deep_copy_node(rnode))
    return merged


def _merge_one_node(lnode: dict, rnode: dict) -> dict:
    """同名カテゴリ 1 対をマージ."""
    return {
        **lnode,
        "name": lnode.get("name"),
        "variables": _merge_variables(
            lnode.get("variables") or [], rnode.get("variables") or []
        ),
        "children": _merge_nodes(
            lnode.get("children") or [], rnode.get("children") or []
        ),
    }


def _merge_variables(local_vars: list, remote_vars: list) -> list:
    """変数 list 同士を name キーで updated_at last-write-wins マージ."""
    by_name_remote = {v.get("name"): v for v in remote_vars if isinstance(v, dict)}
    merged: list = []
    seen: set = set()
    for lv in local_vars:
        if not isinstance(lv, dict):
            continue
        name = lv.get("name")
        seen.add(name)
        rv = by_name_remote.get(name)
        if rv is None:
            merged.append(dict(lv))
        else:
            merged.append(_pick_newer_var(lv, rv))
    for rv in remote_vars:
        if not isinstance(rv, dict):
            continue
        if rv.get("name") in seen:
            continue
        merged.append(dict(rv))
    return merged


def _pick_newer_var(lv: dict, rv: dict) -> dict:
    """updated_at の新しい方を採用（未設定は最古扱い）."""
    lt = lv.get("updated_at") or ""
    rt = rv.get("updated_at") or ""
    return dict(rv) if rt > lt else dict(lv)


def _deep_copy_node(node: dict) -> dict:
    """カテゴリノードを再帰的に shallow copy（変数 dict も新規 dict 化）."""
    return {
        **node,
        "variables": [dict(v) for v in (node.get("variables") or []) if isinstance(v, dict)],
        "children": [_deep_copy_node(c) for c in (node.get("children") or []) if isinstance(c, dict)],
    }


def _backup_path(vars_path: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    candidate = f"{vars_path}.bak.{ts}"
    counter = 1
    while os.path.exists(candidate):
        candidate = f"{vars_path}.bak.{ts}-{counter}"
        counter += 1
    return candidate


def get_variable(variables_map: dict[str, list[str]], name: str) -> Optional[list[str]]:
    return variables_map.get(name)


# ============================================================
#  Phase C: v1 → v2 自動 migration
# ============================================================

def migrate_v1_to_v2_if_needed(path: str) -> Optional[str]:
    """v1 schema を検出したら v2 ツリー形式に変換して再保存. .bak.{ts} を残す.

    v1 の各 entry は category 名でグルーピングされ、values は ", " 結合で
    positive 1 文字列に変換、negative は空文字列で初期化される。

    Returns:
        作成した .bak のパス、何もしなかった場合 (ファイル無 / v2 / 破損) は None。
    """
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None

    entries = data.get("variables") or []
    categories_by_name: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        values = entry.get("values") or []
        if not isinstance(name, str):
            continue
        cat_name = entry.get("category") or "uncategorized"
        positive = ", ".join(str(v) for v in values) if values else ""
        cat = categories_by_name.setdefault(cat_name, {
            "name": cat_name, "children": [], "variables": []
        })
        cat["variables"].append({
            "name": name,
            "positive": positive,
            "negative": "",
        })
    tree = list(categories_by_name.values())
    return save_variables_v2(path, tree)
