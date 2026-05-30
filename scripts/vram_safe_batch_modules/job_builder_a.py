"""
job_builder_a.py - 改善案1用ジョブ構築モジュール

【モード】直積（全組み合わせ）+ オーバーライドルール

【オーバーライドルールの書き方】
  条件に一致する組み合わせの特定要素を差し替えます。

  書式:
    リスト内容A, リスト内容B + リスト内容C → リスト番号:差し替え内容

  例:
    教師A, 教師B + 制服 → {2}:スーツ
    → リスト{1}が「教師A」または「教師B」かつリスト{2}が「制服」の場合、
      リスト{2}の値を「スーツ」に差し替える

  複数ルールは改行で区切る:
    教師A, 教師B + 制服 → {2}:スーツ
    生徒D + 状態2 → {3}:特殊状態X

  skipで組み合わせを除外:
    教師A + 状態4 → skip
    → この組み合わせは生成しない

【ルールの優先順位】
  上から順に適用。複数ルールが同じ要素を変更する場合は後のルールが優先。
"""

import itertools
import re


def parse_slot(text):
    """1つのスロットテキストを解析して (内容, 枚数override or None) のリストを返す"""
    entries = []
    if not text or not text.strip():
        return entries

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        count_override = None
        if "|" in line:
            parts = line.rsplit("|", 1)
            try:
                count_override = int(parts[1].strip())
                count_override = max(1, min(count_override, 50))
                line = parts[0].strip()
            except ValueError:
                pass

        entries.append((line, count_override))
    return entries


def parse_override_rules(rules_text):
    """オーバーライドルールテキストを解析する
    
    書式: 条件内容A, 条件内容B + 条件内容C → {N}:差し替え内容
    または: 条件内容A + 条件内容B → skip
    
    Returns:
        list of dict: ルールのリスト
    """
    rules = []
    if not rules_text or not rules_text.strip():
        return rules

    for line in rules_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # → で条件と結果に分割
        if "→" not in line:
            continue

        parts = line.split("→", 1)
        condition_str = parts[0].strip()
        result_str = parts[1].strip()

        # 条件を解析（+で複数条件を結合）
        conditions = []
        for cond in condition_str.split("+"):
            cond = cond.strip()
            # カンマ区切りで複数値（OR条件）
            values = [v.strip() for v in cond.split(",") if v.strip()]
            if values:
                conditions.append(values)

        # 結果を解析
        if result_str.lower() == "skip":
            action = {"type": "skip"}
        else:
            # {N}:差し替え内容 の形式
            match = re.match(r'\{(\d+)\}:(.*)', result_str)
            if match:
                slot_idx = int(match.group(1))
                replacement = match.group(2).strip()
                action = {"type": "replace", "slot_idx": slot_idx, "value": replacement}
            else:
                print(f"  ⚠ ルール解析エラー（スキップ）: {line}")
                continue

        rules.append({
            "conditions": conditions,
            "action": action,
            "raw": line
        })

    return rules


def apply_override_rules(combo, active_slot_indices, rules):
    """組み合わせにオーバーライドルールを適用する
    
    Returns:
        (skip, modified_combo)
        skip: Trueならこの組み合わせを生成しない
        modified_combo: ルール適用後の組み合わせ
    """
    # comboをリストに変換（変更可能にする）
    modified = list(combo)

    for rule in rules:
        conditions = rule["conditions"]
        action = rule["action"]

        # 全条件が一致するか確認
        all_match = True
        for cond_values in conditions:
            # comboの中にcond_valuesのいずれかが含まれるか
            found = False
            for item_content, _ in modified:
                if item_content in cond_values:
                    found = True
                    break
            if not found:
                all_match = False
                break

        if not all_match:
            continue

        # 条件一致 → アクションを適用
        if action["type"] == "skip":
            return True, None
        elif action["type"] == "replace":
            slot_idx = action["slot_idx"]
            # active_slot_indicesからリスト番号に対応するcomboのインデックスを探す
            try:
                combo_idx = active_slot_indices.index(slot_idx)
                original_count = modified[combo_idx][1]
                modified[combo_idx] = (action["value"], original_count)
            except ValueError:
                print(f"  ⚠ リスト{{{slot_idx}}}が見つかりません: {rule['raw']}")

    return False, tuple(modified)


def build_jobs(all_slots, active_slot_indices, default_count, rules):
    """全組み合わせとジョブリストを構築する（オーバーライドルール適用）"""
    combinations = list(itertools.product(*all_slots))

    jobs = []
    total_images = 0
    skipped = 0

    for combo in combinations:
        # オーバーライドルールを適用
        skip, modified_combo = apply_override_rules(combo, active_slot_indices, rules)

        if skip:
            skipped += 1
            continue

        count = 1
        for c in modified_combo:
            item_count = c[1] if c[1] is not None else default_count
            count *= item_count

        jobs.append((modified_combo, count))
        total_images += count

    if skipped > 0:
        print(f"  オーバーライドルールにより {skipped} 組み合わせをスキップ")

    return combinations, jobs, total_images


def build_prompt(original_prompt, combo, used_placeholders, active_slot_indices):
    """組み合わせからプロンプトを構築する"""
    replaced_prompt = original_prompt

    if used_placeholders:
        for slot_order, slot_idx in enumerate(active_slot_indices):
            placeholder = "{" + str(slot_idx) + "}"
            if placeholder in replaced_prompt:
                replaced_prompt = replaced_prompt.replace(
                    placeholder, combo[slot_order][0]
                )
    else:
        prefix = " ".join(c[0] for c in combo)
        replaced_prompt = prefix + " " + replaced_prompt

    return replaced_prompt
