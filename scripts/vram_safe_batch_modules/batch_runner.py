"""
batch_runner.py - v3b 生成ループ本体 (Phase 8-A3 抽出)

v3b.py の _run_internal から抽出したモジュールレベル関数。
動作・出力・ログは元コードと完全に同一。
"""

import os

import modules.shared as shared
from modules.processing import process_images, Processed

from . import expander, variables_store, history_v2, progress, image_generator, vram_manager
from .ui_helpers import _parse_dropdown_index

# 安全上限（元 v3b.py の MAX_IMAGES_WARNING と同値）
MAX_IMAGES_WARNING = 100


def run_batch(p, history_dropdown, resume_check, *, repo_root):
    """v3b の生成ループ本体。

    Args:
        p: StableDiffusionProcessingTxt2Img
        history_dropdown, resume_check: UI 値 (履歴・再開)
        repo_root: リポジトリルート絶対パス (`vars/variables.json` を引くために必要)

    expansion_order / seed_mode は prompt_expander が p._pe_expansion_order /
    p._pe_seed_mode に stash した値から取得する。未設定時は auto-order / "sequential"。
    """
    base_dir = repo_root

    # ==========================================
    #  再開モード判定
    # ==========================================
    history_index = _parse_dropdown_index(history_dropdown)
    entries = history_v2.load_history(base_dir)
    resume_mode = False
    resume_entry = None
    skip_until = 0

    if resume_check and 0 <= history_index < len(entries):
        resume_entry = entries[history_index]
        pr = resume_entry.get("progress", {})
        if pr.get("status") in ("running", "interrupted"):
            resume_mode = True
            skip_until = pr.get("completed", 0)
            print(f"\n{'='*50}")
            print(f" 再開モード: 履歴{history_index+1}の設定を使用")
            print(f" {skip_until}枚目まで完了済み → {skip_until+1}枚目から再開")
            print(f"{'='*50}")

    # ==========================================
    #  プロンプト・変数の取得
    # ==========================================
    _variables_path = os.path.join(repo_root, "vars", "variables.json")

    if resume_mode and resume_entry:
        ep = resume_entry.get("prompt", {})
        main_prompt = ep.get("main", p.prompt)
        negative = ep.get("negative", p.negative_prompt)
        saved_order = ep.get("expansion_order", [])
        saved_vars = ep.get("used_variables", {})

        # generation 設定を p に反映
        g = resume_entry.get("generation", {})
        p.prompt = main_prompt
        p.negative_prompt = negative
        p.width = g.get("width", p.width)
        p.height = g.get("height", p.height)
        p.cfg_scale = g.get("cfg_scale", p.cfg_scale)
        p.steps = g.get("steps", p.steps)
        p.sampler_name = g.get("sampler", p.sampler_name)
        if hasattr(p, "scheduler"):
            p.scheduler = g.get("scheduler", p.scheduler)
        # §2: resume 時は seed_mode / resolved_initial_seed を復元
        seed_mode = g.get("seed_mode", "sequential")
        resolved_initial_seed = g.get(
            "resolved_initial_seed",
            g.get("initial_seed", p.seed),
        )
        p.seed = resolved_initial_seed

        parsed = expander.parse_main_prompt(main_prompt)
        # resume 時は履歴に保存された used_variables を優先使用
        merged = expander.merge_variables(parsed.inline_vars, saved_vars)
        order = saved_order

        vram_manager.reload_model()
    else:
        # === 新規モード ===
        main_prompt = p.prompt or ""
        negative = p.negative_prompt or ""

        # prompt_expander が事前展開済みかチェック
        pe_prompts = list(getattr(p, "all_prompts", []) or [])
        if len(pe_prompts) > 1:
            # prompt_expander の結果を信頼する
            expanded_prompts = pe_prompts
            pe_negatives = list(getattr(p, "all_negative_prompts", []) or [])
            effective_negative = pe_negatives[0] if pe_negatives else negative
            pe_seeds = list(getattr(p, "all_seeds", []) or [])
            # 履歴記録用に order / seed_mode / resolved_initial_seed を計算
            # p._pe_expansion_order / p._pe_seed_mode は prompt_expander が stash した値
            parsed = expander.parse_main_prompt(main_prompt)
            json_vars = variables_store.load_variables(_variables_path)
            merged = expander.merge_variables(parsed.inline_vars, json_vars)
            order = list(getattr(p, "_pe_expansion_order", None) or [])
            if not order:
                used = expander.extract_used_variables(parsed.body, merged)
                order = [v for v in used if v in merged]
            seed_mode = getattr(p, "_pe_seed_mode", None) or "sequential"
            if seed_mode not in ("fixed", "sequential"):
                seed_mode = "sequential"
            # prompt_expander が seed_mode を考慮済みなので、initial_seed は all_seeds[0]
            resolved_initial_seed = (pe_seeds[0] if pe_seeds and pe_seeds[0] != -1
                                     else progress.resolve_initial_seed(p.seed))
            # all_seeds の -1 は実際の乱択値が分からないので resolved に補正
            if pe_seeds and any(s == -1 for s in pe_seeds):
                pe_seeds = [(s if s != -1 else resolved_initial_seed + (i if seed_mode == "sequential" else 0))
                            for i, s in enumerate(pe_seeds)]
            precomputed_seeds = pe_seeds if pe_seeds else None
        else:
            # Fallback: 自前で展開 (prompt_expander OFF や $変数なしの場合)
            parsed = expander.parse_main_prompt(main_prompt)
            json_vars = variables_store.load_variables(_variables_path)
            merged = expander.merge_variables(parsed.inline_vars, json_vars)
            # p._pe_expansion_order を使い、無ければ auto-order
            order = list(getattr(p, "_pe_expansion_order", None) or [])
            if not order:
                used = expander.extract_used_variables(parsed.body, merged)
                order = [v for v in used if v in merged]
            seed_mode = getattr(p, "_pe_seed_mode", None) or "sequential"
            if seed_mode not in ("fixed", "sequential"):
                seed_mode = "sequential"
            resolved_initial_seed = progress.resolve_initial_seed(p.seed)
            expanded_prompts = expander.expand_prompts(parsed.body, merged, order)
            try:
                negative_dict = variables_store.load_negative_dict(_variables_path)
            except Exception:
                negative_dict = {}
            neg_additions = expander.collect_negative_additions(parsed.body, merged, negative_dict)
            effective_negative = expander.compose_negative_prompt(negative, neg_additions)
            if neg_additions:
                print(f"[v3b] ネガティブ自動追加: {neg_additions}")
            precomputed_seeds = None

    # ==========================================
    #  resume モード時のみ、ここで expanded_prompts と effective_negative を計算
    # ==========================================
    if resume_mode:
        if parsed.has_legacy_n_notation:
            print("[vram_safe_batch] ⚠ 警告: 旧 {N} 記法は廃止されました。$変数 記法を使用してください")
        expanded_prompts = expander.expand_prompts(parsed.body, merged, order)
        try:
            negative_dict = variables_store.load_negative_dict(_variables_path)
        except Exception:
            negative_dict = {}
        neg_additions = expander.collect_negative_additions(parsed.body, merged, negative_dict)
        effective_negative = expander.compose_negative_prompt(negative, neg_additions)
        if neg_additions:
            print(f"[v3b] ネガティブ自動追加: {neg_additions}")
        precomputed_seeds = None

    total_images = len(expanded_prompts)

    if total_images == 0:
        print("展開結果が空です。通常生成を行います。")
        return process_images(p)

    # resume 時は履歴データで p を完全に上書きする (prompt_expander の出力を捨てる)
    if resume_mode:
        p.all_prompts = expanded_prompts
        p.all_negative_prompts = [effective_negative] * total_images
        p.all_seeds = [progress.compute_seed(seed_mode, resolved_initial_seed, i + 1)
                       for i in range(total_images)]
        p.n_iter = total_images
        p.batch_size = 1

    remaining = total_images - skip_until
    if remaining > MAX_IMAGES_WARNING:
        print(f"\n⚠⚠⚠ 警告: 残り{remaining}枚の生成が予定されています")
        print(f"  途中で Interrupt で中断できます")
        print(f"⚠⚠⚠\n")

    # ==========================================
    #  履歴に進捗を保存（新規の場合）
    # ==========================================
    if not resume_mode:
        used_vars_for_history = {name: merged.get(name, []) for name in order if name in merged}
        entry = history_v2.create_entry(
            prompt_main=main_prompt,
            prompt_negative=negative,
            expansion_order=order,
            used_variables=used_vars_for_history,
            generation={
                "width": p.width,
                "height": p.height,
                "cfg_scale": p.cfg_scale,
                "steps": p.steps,
                "sampler": p.sampler_name,
                "scheduler": getattr(p, "scheduler", "Automatic"),
                "initial_seed": p.seed,
                "resolved_initial_seed": resolved_initial_seed,
                "seed_mode": seed_mode,
                "clip_skip": getattr(p, "clip_skip", 1),
            },
        )
        entry["progress"]["total"] = total_images
        history_v2.add_entry(base_dir, entry)
        resume_entry = entry  # update_entry のために id を保持

    entry_id = resume_entry["id"]

    # ==========================================
    #  生成ループ
    # ==========================================
    all_images, all_seeds, all_prompts = [], [], []
    all_negative_prompts, all_infotexts = [], []

    global_num = 0
    last_confirmed_num = skip_until
    interrupted = False

    print(f"\n{'='*50}")
    print(f" VRAM Safe Batch v3b [メインプロンプト統合]")
    if resume_mode:
        print(f" 再開モード: {skip_until}枚完了済み → 残り{remaining}枚")
    print(f" 展開順: {order}")
    print(f" 合計生成枚数: {total_images}")
    print(f" シードモード: {seed_mode} / 解決後初期シード: {resolved_initial_seed}")
    print(f"{'='*50}")

    # クラス共有の prompt conditioning キャッシュ (cached_c / cached_uc) を
    # 念のためクリア。プロンプトが毎回大きく変わるため tensor shape の取り違えを防ぐ。
    try:
        p.clear_prompt_cache()
    except Exception:
        pass

    for prompt_text in expanded_prompts:
        if interrupted:
            break

        global_num += 1
        if global_num <= skip_until:
            if global_num % 50 == 0 or global_num == skip_until:
                print(f"  スキップ中... {global_num}/{skip_until}")
            continue

        if shared.state.interrupted:
            print(f"\n⚡ 中断されました（{last_confirmed_num}/{total_images}枚完了）")
            interrupted = True
            break

        display = prompt_text[:80] + ("..." if len(prompt_text) > 80 else "")
        print(f"\n[{global_num}/{total_images}] {display} 生成中...")

        if precomputed_seeds and global_num - 1 < len(precomputed_seeds):
            seed = precomputed_seeds[global_num - 1]
        else:
            seed = progress.compute_seed(seed_mode, resolved_initial_seed, global_num)
        success, result, is_interrupted = image_generator.generate_one(
            p, prompt_text, seed, effective_negative
        )

        if is_interrupted and not success:
            interrupted = True
            break

        if success:
            image_generator.collect_result(
                result, prompt_text, p,
                all_images, all_seeds, all_prompts,
                all_negative_prompts, all_infotexts,
            )
            # §3: 中断時は部分結果が返ってきても completed をバンプしない。
            # resume すれば同じ画像番号 (global_num) から再生成される（歯抜け回避）。
            if progress.should_update_completed(success, is_interrupted):
                last_confirmed_num = global_num
                history_v2.update_entry(
                    base_dir, entry_id,
                    progress={"completed": last_confirmed_num, "total": total_images, "status": "running"},
                )

            if is_interrupted:
                interrupted = True
                break
        else:
            interrupted = True
            break

    # ==========================================
    #  完了処理
    # ==========================================
    final_status = "completed" if (not interrupted and last_confirmed_num >= total_images) else "interrupted"
    history_v2.update_entry(
        base_dir, entry_id,
        progress={"completed": last_confirmed_num, "total": total_images, "status": final_status},
    )

    status_label = "中断" if interrupted else "完了"
    print(f"\n{'='*50}")
    print(f" {status_label}: {len(all_images)}枚生成しました（{last_confirmed_num}/{total_images}枚確認済み）")
    print(f"{'='*50}\n")

    return Processed(
        p,
        images_list=all_images,
        seed=all_seeds[0] if all_seeds else p.seed,
        info=all_infotexts[0] if all_infotexts else "",
        all_seeds=all_seeds,
        all_prompts=all_prompts,
        all_negative_prompts=all_negative_prompts,
        infotexts=all_infotexts,
    )
