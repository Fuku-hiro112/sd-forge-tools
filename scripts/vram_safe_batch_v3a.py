"""
vram_safe_batch_v3a.py - VRAM Safe Batch v3a
直積（全組み合わせ）+ オーバーライドルール方式

【設置方法】
1. このファイルを scripts/ フォルダに置く
2. vram_safe_batch_modules/ フォルダを scripts/ フォルダ内に置く
3. WebUIを再起動する

【使い方】
1. WebUIで普段通りプロンプト・設定を行う
2. Scriptドロップダウンから「VRAM Safe Batch v3a [直積+オーバーライド]」を選択
3. 各リストスロットに値を入力（1行1項目）
4. 必要に応じてオーバーライドルールを入力
5. Generateボタンを押す

【プロンプトの書き方】
  メインプロンプト欄に {1}, {2}, {3}... でリストを参照:
    masterpiece, best quality, {1}, 1girl, {2}, {3}

【リストの書き方】
  1行1項目。末尾に |数字 で枚数指定（掛け算）。
  例:
    shinosawa hiro
    hanami saki|3

【オーバーライドルールの書き方】
  条件に一致する組み合わせの要素を差し替えます。
  書式: 条件A, 条件B + 条件C → {N}:差し替え内容
  例:
    教師A, 教師B + 制服 → {2}:スーツ
    生徒D + 状態2 → {3}:特殊状態X
    教師A + 状態4 → skip  ← この組み合わせを除外

【途中再開】
  エラーやPC再起動で中断後、WebUI起動→スクリプト選択→
  ドロップダウンで履歴を選択→「選択した履歴から再開」にチェック→Generate
"""

import os
import sys

# モジュールパスを追加（vram_safe_batch_modulesはscripts/フォルダ内に配置）
sys.path.insert(0, os.path.dirname(__file__))

import gradio as gr
import modules.scripts as scripts
import modules.shared as shared
from modules.processing import process_images, Processed

from vram_safe_batch_modules import progress, vram_manager, image_generator, job_builder_a

# 再帰防止フラグ
_running = False

# スロット数
NUM_SLOTS = 10

# 安全上限
MAX_IMAGES_WARNING = 100


class VRAMSafeBatchV3A(scripts.Script):

    def title(self):
        return "VRAM Safe Batch v3a [直積+オーバーライド]"

    def show(self, is_img2img):
        return True

    def _base_dir(self):
        return os.path.join(os.path.dirname(__file__), '..')

    def ui(self, is_img2img):
        base_dir = self._base_dir()

        gr.Markdown("## VRAM Safe Batch v3a — 直積 + オーバーライドルール方式")
        gr.Markdown(
            "リスト{1}〜{10}の全組み合わせを生成します。"
            "オーバーライドルールで特定の組み合わせの要素を差し替えたり除外できます。"
            "プロンプトに `{1}`, `{2}` ... を書くと、そこにリストの内容が入ります。"
        )

        # ==========================================
        #  履歴・再開セクション
        # ==========================================
        gr.Markdown("### 途中再開")

        choices = progress.get_dropdown_choices(base_dir)
        history_dropdown = gr.Dropdown(
            choices=choices,
            label="再開する履歴を選択",
            value=choices[0] if choices else None,
            info="中断した履歴を選択して続きから再開できます（最大5件保持）"
        )

        history_detail = gr.Textbox(
            label="選択中の履歴詳細",
            value=self._get_detail(base_dir, 0),
            interactive=False,
            lines=6,
        )

        resume_check = gr.Checkbox(
            label="選択した履歴から再開する",
            value=False,
            info="チェックONの場合、入力欄の設定は無視され選択した履歴の設定が使われます"
        )

        # ドロップダウン変更時に詳細を更新
        def on_dropdown_change(choice):
            if not choice or choice == "履歴なし":
                return ""
            try:
                idx = int(choice.split(".")[0]) - 1
                return progress.get_entry_detail(base_dir, idx)
            except Exception:
                return ""

        history_dropdown.change(
            fn=on_dropdown_change,
            inputs=[history_dropdown],
            outputs=[history_detail]
        )

        # ==========================================
        #  生成設定セクション
        # ==========================================
        gr.Markdown("### 生成設定")

        default_count = gr.Slider(
            minimum=1,
            maximum=20,
            step=1,
            value=1,
            label="デフォルト生成枚数",
            info="各組み合わせの枚数。各項目の枚数を掛け算。個別に |数字 で上書き可。"
        )

        # ==========================================
        #  リストスロット
        # ==========================================
        gr.Markdown(
            "### リスト\n"
            "1行1項目。末尾に `|数字` で枚数指定（例: `hanami saki|3`）。\n"
            "枚数は各列の値を掛け算します。"
        )

        slots = []
        for i in range(1, NUM_SLOTS + 1):
            slot = gr.Textbox(
                label=f"リスト{{{i}}}",
                placeholder=f"1行に1項目（枚数上書き: 項目|数字）",
                lines=3,
            )
            slots.append(slot)

        # ==========================================
        #  オーバーライドルール
        # ==========================================
        gr.Markdown(
            "### オーバーライドルール（任意）\n"
            "書式: `条件A, 条件B + 条件C → {N}:差し替え内容`\n"
            "除外: `条件A + 条件B → skip`\n"
            "例: `教師A, 教師B + 制服 → {2}:スーツ`"
        )

        override_rules = gr.Textbox(
            label="オーバーライドルール",
            placeholder="教師A, 教師B + 制服 → {2}:スーツ\n生徒D + 状態2 → {3}:特殊状態X",
            lines=5,
        )

        return [history_dropdown, resume_check, default_count, override_rules] + slots

    def _get_detail(self, base_dir, index):
        detail = progress.get_entry_detail(base_dir, index)
        return detail

    def _parse_dropdown_index(self, choice):
        if not choice or choice == "履歴なし":
            return -1
        try:
            return int(choice.split(".")[0]) - 1
        except Exception:
            return -1

    def run(self, p, history_dropdown, resume_check, default_count, override_rules, *slot_texts):
        global _running
        if _running:
            return process_images(p)
        _running = True
        try:
            return self._run_internal(p, history_dropdown, resume_check,
                                      default_count, override_rules, slot_texts)
        finally:
            _running = False

    def _run_internal(self, p, history_dropdown, resume_check,
                      default_count, override_rules, slot_texts):
        base_dir = self._base_dir()
        default_count = int(default_count)

        # ==========================================
        #  再開モード判定
        # ==========================================
        history_index = self._parse_dropdown_index(history_dropdown)
        resume_mode = False
        skip_until = 0
        history_entry = None

        if resume_check and history_index >= 0:
            if progress.is_resumable(base_dir, history_index):
                history_entry = progress.get_entry(base_dir, history_index)
                resume_mode = True
                skip_until = history_entry.get("completed", 0)
                print(f"\n{'='*50}")
                print(f" 再開モード: 履歴{history_index+1}の設定を使用")
                print(f" {skip_until}枚目まで完了済み → {skip_until+1}枚目から再開")
                print(f"{'='*50}")

        # ==========================================
        #  設定の決定
        # ==========================================
        if resume_mode and history_entry:
            original_prompt = history_entry["prompt"]
            initial_seed = history_entry.get("seed", -1)
            default_count = history_entry.get("default_count", 1)

            # pに設定を反映
            p.prompt = original_prompt
            p.negative_prompt = history_entry.get("negative_prompt", p.negative_prompt)
            p.width = history_entry.get("width", p.width)
            p.height = history_entry.get("height", p.height)
            p.cfg_scale = history_entry.get("cfg_scale", p.cfg_scale)
            p.steps = history_entry.get("steps", p.steps)
            p.sampler_name = history_entry.get("sampler", p.sampler_name)
            if hasattr(p, 'scheduler'):
                p.scheduler = history_entry.get("scheduler", p.scheduler)
            p.seed = initial_seed

            # スロットを復元
            all_slots = []
            active_slot_indices = []
            saved_slots = history_entry.get("slots", [])
            saved_counts = history_entry.get("slot_counts", [])
            saved_indices = history_entry.get("active_indices", list(range(1, len(saved_slots)+1)))

            for i, (slot_lines, slot_cnts) in enumerate(zip(saved_slots, saved_counts)):
                entries = [(line, cnt) for line, cnt in zip(slot_lines, slot_cnts)]
                if entries:
                    all_slots.append(entries)
                    active_slot_indices.append(saved_indices[i])

            # オーバーライドルールも復元
            saved_rules_text = history_entry.get("override_rules", "")
            rules = job_builder_a.parse_override_rules(saved_rules_text)

            # モデルキャッシュをクリア
            vram_manager.reload_model()

        else:
            original_prompt = p.prompt
            initial_seed = p.seed

            all_slots = []
            active_slot_indices = []
            raw_slots = []
            raw_counts = []

            for i, text in enumerate(slot_texts):
                entries = job_builder_a.parse_slot(text)
                if entries:
                    all_slots.append(entries)
                    active_slot_indices.append(i + 1)
                    raw_slots.append([e[0] for e in entries])
                    raw_counts.append([e[1] for e in entries])

            rules = job_builder_a.parse_override_rules(override_rules)

        if not all_slots:
            print("リストが空です。通常生成を行います。")
            return process_images(p)

        # ==========================================
        #  ジョブ構築
        # ==========================================
        combinations, jobs, total_images = job_builder_a.build_jobs(
            all_slots, active_slot_indices, default_count, rules
        )

        used_placeholders = [
            idx for idx in active_slot_indices
            if "{" + str(idx) + "}" in original_prompt
        ]

        if not used_placeholders:
            print(f"⚠ プロンプトに {{N}} が見つかりません → プロンプト先頭に追加します")

        remaining = total_images - skip_until
        if remaining > MAX_IMAGES_WARNING:
            print(f"\n⚠⚠⚠ 警告: 残り{remaining}枚の生成が予定されています")
            print(f"  途中でInterruptで中断できます")
            print(f"⚠⚠⚠\n")

        # ==========================================
        #  進捗を履歴に保存（新規の場合）
        # ==========================================
        if not resume_mode:
            raw_slots_save = [[e[0] for e in s] for s in all_slots]
            raw_counts_save = [[e[1] for e in s] for s in all_slots]
            history_index = progress.create_new_progress(
                base_dir=base_dir,
                prompt=original_prompt,
                negative_prompt=p.negative_prompt,
                width=p.width,
                height=p.height,
                cfg_scale=p.cfg_scale,
                steps=p.steps,
                sampler=p.sampler_name,
                scheduler=getattr(p, 'scheduler', 'Automatic'),
                seed=initial_seed,
                clip_skip=getattr(p, 'clip_skip', 1),
                default_count=default_count,
                slots=raw_slots_save,
                slot_counts=raw_counts_save,
                active_indices=active_slot_indices,
                total=total_images,
            )
            # オーバーライドルールも保存
            hist = progress.load_history(base_dir)
            hist[0]["override_rules"] = override_rules or ""
            progress.save_history(base_dir, hist)

        # ==========================================
        #  生成ループ
        # ==========================================
        all_images, all_seeds, all_prompts = [], [], []
        all_negative_prompts, all_infotexts = [], []

        global_num = 0
        last_confirmed_num = skip_until
        interrupted = False

        print(f"\n{'='*50}")
        print(f" VRAM Safe Batch v3a [直積+オーバーライド]")
        if resume_mode:
            print(f" 再開モード: {skip_until}枚完了済み → 残り{remaining}枚")
        print(f" アクティブリスト: {len(all_slots)}個 (リスト {active_slot_indices})")
        print(f" 組み合わせ数: {len(jobs)}")
        print(f" デフォルト枚数: {default_count}")
        print(f" 合計生成枚数: {total_images}")
        if rules:
            print(f" オーバーライドルール: {len(rules)}件")
        print(f"{'='*50}")

        for combo, count in jobs:
            if interrupted:
                break

            for j in range(count):
                global_num += 1

                if global_num <= skip_until:
                    if global_num % 50 == 0 or global_num == skip_until:
                        print(f"  スキップ中... {global_num}/{skip_until}")
                    continue

                if shared.state.interrupted:
                    print(f"\n⚡ 中断されました（{last_confirmed_num}/{total_images}枚完了）")
                    interrupted = True
                    break

                suffix = f" ({j+1}/{count})" if count > 1 else ""
                combo_display = " × ".join(
                    c[0][:20] + "..." if len(c[0]) > 20 else c[0]
                    for c in combo
                )
                print(f"\n[{global_num}/{total_images}] {combo_display}{suffix} 生成中...")

                replaced_prompt = job_builder_a.build_prompt(
                    original_prompt, combo, used_placeholders, active_slot_indices
                )

                seed = -1 if initial_seed == -1 else initial_seed + (global_num - 1)
                success, result, is_interrupted = image_generator.generate_one(
                    p, replaced_prompt, seed
                )

                if is_interrupted and not success:
                    interrupted = True
                    break

                if success:
                    image_generator.collect_result(
                        result, replaced_prompt, p,
                        all_images, all_seeds, all_prompts,
                        all_negative_prompts, all_infotexts
                    )
                    last_confirmed_num = global_num
                    progress.update_completed(base_dir, history_index, last_confirmed_num)

                    if is_interrupted:
                        interrupted = True
                        break
                else:
                    interrupted = True
                    break

                if global_num < total_images:
                    print("  VRAM解放中...")
                    vram_manager.free_vram()

        # ==========================================
        #  完了処理
        # ==========================================
        if not interrupted and last_confirmed_num >= total_images:
            progress.mark_completed(base_dir, history_index)

        status = "中断" if interrupted else "完了"
        print(f"\n{'='*50}")
        print(f" {status}: {len(all_images)}枚生成しました（{last_confirmed_num}/{total_images}枚確認済み）")
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
