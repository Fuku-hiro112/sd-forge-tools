"""
VRAM Safe Batch v3 - 汎用リスト組み合わせ生成スクリプト（進捗保存＋途中再開対応）

【設置方法】
このファイルを以下のフォルダに置いてWebUIを再起動：
  stable-diffusion-webui-forge/scripts/

【使い方】
1. WebUIで普段通りプロンプトやネガティブプロンプト、解像度等を設定
2. 左下の「Script」ドロップダウンから「VRAM Safe Batch v3」を選択
3. メインプロンプト欄に {1}, {2}, {3}... でリストの参照を書く
4. 各リストスロットに値を入力（1行1項目）
5. デフォルト枚数を設定
6. Generateボタンを押す

【途中再開】
エラーやPC再起動で中断された場合：
1. WebUIを起動
2. スクリプト「VRAM Safe Batch v3」を選択
3. 「前回の続きから再開する」にチェックが入っていることを確認
4. そのままGenerateを押す（入力欄は空でOK、進捗ファイルから復元されます）

【プロンプトの書き方】
  メインプロンプト欄に:
    masterpiece, best quality, {1} {2}, 1girl, solo, {3}

【リストの書き方】
  各リストスロットに1行1項目。枚数指定は |数字 で。

【枚数指定】
  各項目の枚数を掛け算で計算。|数字 がない項目はデフォルト値。
"""

import re
import gc
import os
import json
import itertools
import torch
import gradio as gr
import modules.scripts as scripts
import modules.shared as shared
from modules.processing import process_images, Processed, StableDiffusionProcessingTxt2Img


_running = False

NUM_SLOTS = 10
MAX_IMAGES_WARNING = 100
MAX_COUNT_OVERRIDE = 50

PROGRESS_FILE = os.path.normpath(
    os.path.join(scripts.basedir(), "..", "batch_progress.json")
)
BACKUP_FILE = os.path.normpath(
    os.path.join(scripts.basedir(), "..", "batch_progress_backup.json")
)

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"


class VRAMSafeBatchV3(scripts.Script):

    def title(self):
        return "VRAM Safe Batch v3"

    def show(self, is_img2img):
        return True

    def ui(self, is_img2img):
        resume_info = gr.Textbox(
            label="進捗情報",
            value=self._get_progress_info(),
            interactive=False,
            lines=1,
        )
        resume_check = gr.Checkbox(
            label="前回の続きから再開する",
            value=self._has_resumable_progress(),
            info="チェックONの場合、入力欄の設定は無視され進捗ファイルの設定が使われます。"
        )
        default_count = gr.Slider(
            minimum=1, maximum=20, step=1, value=1,
            label="各項目のデフォルト生成枚数",
            info="各項目の枚数を掛け算。個別に|数字で上書き可。"
        )
        slots = [
            gr.Textbox(
                label=f"リスト{{{i}}}",
                placeholder="1行に1項目（枚数上書き: 項目|数字）",
                lines=3,
            )
            for i in range(1, NUM_SLOTS + 1)
        ]
        return [resume_info, resume_check, default_count] + slots

    # ==========================================
    #  進捗ファイル管理
    # ==========================================

    def load_progress(self):
        if not os.path.exists(PROGRESS_FILE):
            return None
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_progress(self, data):
        try:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  ⚠ 進捗保存エラー: {e}")

    def backup_progress(self):
        try:
            if os.path.exists(PROGRESS_FILE):
                if os.path.exists(BACKUP_FILE):
                    os.remove(BACKUP_FILE)
                os.rename(PROGRESS_FILE, BACKUP_FILE)
                print(f"  進捗ファイルをバックアップしました: {BACKUP_FILE}")
        except Exception as e:
            print(f"  ⚠ バックアップエラー: {e}")

    def mark_completed(self):
        progress = self.load_progress()
        if progress:
            progress["status"] = STATUS_COMPLETED
            self.save_progress(progress)

    def _update_completed(self, completed_num):
        progress = self.load_progress()
        if progress:
            progress["completed"] = completed_num
            self.save_progress(progress)

    def _has_resumable_progress(self):
        data = self.load_progress()
        if not data:
            return False
        return (
            data.get("status") == STATUS_RUNNING
            and data.get("completed", 0) < data.get("total", 0)
        )

    def _get_progress_info(self):
        data = self.load_progress()
        if not data:
            return "前回の進捗: なし"
        status = data.get("status")
        if status == STATUS_RUNNING:
            completed = data.get("completed", 0)
            total = data.get("total", 0)
            if total > 0:
                pct = int(completed / total * 100)
                return f"⚠ 前回の進捗: {total}枚中{completed}枚完了 ({pct}%)"
        elif status == STATUS_COMPLETED:
            return "前回のジョブ: 完了済み"
        return "前回の進捗: なし"

    # ==========================================
    #  リスト解析
    # ==========================================

    def parse_slot(self, text):
        """1つのスロットを解析。空行でブロックに分割し、同一ブロック内の複数行はスペース結合で1エントリ。
        ブロック末尾の行に |数字 があれば枚数を上書き。"""
        if not text or not text.strip():
            return []

        entries = []
        for block in re.split(r'\n\s*\n', text.strip()):
            block = block.strip()
            if not block:
                continue

            count_override = None
            lines = block.splitlines()
            last_line = lines[-1].strip()

            if "|" in last_line:
                head, _, tail = last_line.rpartition("|")
                try:
                    count_override = max(1, min(int(tail.strip()), MAX_COUNT_OVERRIDE))
                    lines[-1] = head.strip()
                except ValueError:
                    pass

            combined = " ".join(l.strip() for l in lines if l.strip())
            if combined:
                entries.append((combined, count_override))

        return entries

    # ==========================================
    #  VRAM管理
    # ==========================================

    def free_vram(self):
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        gc.collect()

    def reload_model(self):
        """モデルをアンロード→リロードしてキャッシュを完全クリア"""
        try:
            import modules.sd_models as sd_models
            print("  モデルキャッシュをクリア中...")
            sd_models.unload_model_weights()
            sd_models.reload_model_weights()
            self.free_vram()
            print("  モデルキャッシュクリア完了")
        except Exception as e:
            print(f"  ⚠ モデルリロードエラー（続行します）: {e}")
            self.free_vram()

    def create_fresh_p(self, original_p, new_prompt):
        """元のpの設定を引き継いだ新しいpオブジェクトを作成"""
        new_p = StableDiffusionProcessingTxt2Img(
            sd_model=original_p.sd_model,
            outpath_samples=original_p.outpath_samples,
            outpath_grids=original_p.outpath_grids,
            prompt=new_prompt,
            negative_prompt=original_p.negative_prompt,
            seed=original_p.seed,
            sampler_name=original_p.sampler_name,
            scheduler=getattr(original_p, 'scheduler', None),
            batch_size=1,
            n_iter=1,
            steps=original_p.steps,
            cfg_scale=original_p.cfg_scale,
            width=original_p.width,
            height=original_p.height,
            tiling=original_p.tiling,
        )
        new_p.do_not_save_samples = False
        new_p.do_not_save_grid = True
        if hasattr(original_p, 'override_settings'):
            new_p.override_settings = original_p.override_settings
        return new_p

    # ==========================================
    #  ジョブ構築
    # ==========================================

    def build_jobs(self, all_slots, default_count):
        """全組み合わせとジョブリストを構築"""
        combinations = list(itertools.product(*all_slots))
        jobs = []
        total_images = 0
        for combo in combinations:
            count = 1
            for _, override in combo:
                count *= override if override is not None else default_count
            jobs.append((combo, count))
            total_images += count
        return combinations, jobs, total_images

    def build_prompt(self, original_prompt, combo, used_placeholders, active_slot_indices):
        """組み合わせからプロンプトを構築"""
        if not used_placeholders:
            prefix = " ".join(c[0] for c in combo)
            return prefix + " " + original_prompt

        replaced = original_prompt
        for slot_order, slot_idx in enumerate(active_slot_indices):
            placeholder = "{" + str(slot_idx) + "}"
            if placeholder in replaced:
                replaced = replaced.replace(placeholder, combo[slot_order][0])
        return replaced

    # ==========================================
    #  メイン実行
    # ==========================================

    def run(self, p, resume_info, resume_check, default_count, *slot_texts):
        global _running
        if _running:
            return process_images(p)

        _running = True
        try:
            return self._run_internal(p, resume_check, default_count, slot_texts)
        finally:
            _running = False

    def _run_internal(self, p, resume_check, default_count, slot_texts):
        default_count = int(default_count)
        resume_mode = bool(resume_check) and self._has_resumable_progress()

        if resume_mode:
            progress_data = self.load_progress()
            skip_until = progress_data.get("completed", 0)
            default_count = progress_data.get("default_count", default_count)
            initial_seed = progress_data.get("seed", -1)

            print(f"\n{'='*50}")
            print(f" 再開モード: 進捗ファイルの設定を使用")
            print(f" {skip_until}枚目まで完了済み → {skip_until + 1}枚目から再開")
            print(f"{'='*50}")

            all_slots, active_slot_indices, original_prompt = \
                self._restore_from_progress(p, progress_data)
            self.reload_model()
        else:
            skip_until = 0
            initial_seed = p.seed
            original_prompt = p.prompt

            if self._has_resumable_progress():
                print("  前回の進捗をバックアップします...")
                self.backup_progress()

            all_slots, active_slot_indices = self._build_from_inputs(slot_texts)

        if not all_slots:
            print("リストが空です。通常生成を行います。")
            return process_images(p)

        combinations, jobs, total_images = self.build_jobs(all_slots, default_count)

        used_placeholders = [
            idx for idx in active_slot_indices
            if "{" + str(idx) + "}" in original_prompt
        ]
        if not used_placeholders:
            print(f"⚠ プロンプトに {{N}} が見つかりません。")
            print(f"  使用中のリスト番号: {active_slot_indices}")
            print(f"  → プロンプト先頭にリストの内容を結合して追加します。")

        remaining = total_images - skip_until
        if remaining > MAX_IMAGES_WARNING:
            print(f"\n⚠⚠⚠ 警告: 残り{remaining}枚の生成が予定されています（上限目安: {MAX_IMAGES_WARNING}枚）")
            print(f"  途中でInterruptで中断できます。")
            print(f"⚠⚠⚠\n")

        if not resume_mode:
            self.save_progress(self._build_progress_snapshot(
                p, original_prompt, initial_seed, default_count,
                all_slots, active_slot_indices, total_images,
            ))

        self._print_header(
            resume_mode, skip_until, remaining,
            all_slots, active_slot_indices, combinations,
            default_count, total_images,
        )

        return self._run_generation_loop(
            p, jobs, total_images, skip_until,
            original_prompt, initial_seed,
            used_placeholders, active_slot_indices,
        )

    def _restore_from_progress(self, p, progress_data):
        """進捗データからpオブジェクトとスロットを復元"""
        p.prompt = progress_data.get("prompt", "")
        p.negative_prompt = progress_data.get("negative_prompt", "")
        p.width = progress_data.get("width", 1024)
        p.height = progress_data.get("height", 1408)
        p.cfg_scale = progress_data.get("cfg_scale", 5)
        p.steps = progress_data.get("steps", 20)
        p.sampler_name = progress_data.get("sampler", "DPM++ 2M")
        if hasattr(p, 'scheduler'):
            p.scheduler = progress_data.get("scheduler", "Automatic")
        p.seed = progress_data.get("seed", -1)

        saved_slots = progress_data.get("slots", [])
        saved_counts = progress_data.get("slot_counts", [])
        active_indices = progress_data.get(
            "active_indices", list(range(1, len(saved_slots) + 1))
        )

        all_slots = []
        active_slot_indices = []
        for i, (slot_lines, slot_cnts) in enumerate(zip(saved_slots, saved_counts)):
            entries = list(zip(slot_lines, slot_cnts))
            if entries:
                all_slots.append(entries)
                active_slot_indices.append(active_indices[i])

        return all_slots, active_slot_indices, p.prompt

    def _build_from_inputs(self, slot_texts):
        """UI入力テキストからスロットを構築"""
        all_slots = []
        active_slot_indices = []
        for i, text in enumerate(slot_texts):
            entries = self.parse_slot(text)
            if entries:
                all_slots.append(entries)
                active_slot_indices.append(i + 1)
        return all_slots, active_slot_indices

    def _build_progress_snapshot(self, p, original_prompt, initial_seed,
                                 default_count, all_slots, active_slot_indices,
                                 total_images):
        return {
            "status": STATUS_RUNNING,
            "prompt": original_prompt,
            "negative_prompt": p.negative_prompt,
            "width": p.width,
            "height": p.height,
            "cfg_scale": p.cfg_scale,
            "steps": p.steps,
            "sampler": p.sampler_name,
            "scheduler": getattr(p, 'scheduler', "Automatic"),
            "seed": initial_seed,
            "clip_skip": getattr(p, 'clip_skip', 1),
            "default_count": default_count,
            "slots": [[e[0] for e in s] for s in all_slots],
            "slot_counts": [[e[1] for e in s] for s in all_slots],
            "active_indices": active_slot_indices,
            "completed": 0,
            "total": total_images,
        }

    def _print_header(self, resume_mode, skip_until, remaining, all_slots,
                      active_slot_indices, combinations, default_count, total_images):
        print(f"\n{'='*50}")
        print(f" VRAM Safe Batch v3")
        if resume_mode:
            print(f" 再開モード: {skip_until}枚完了済み → 残り{remaining}枚")
        print(f" アクティブリスト: {len(all_slots)}個 (リスト {active_slot_indices})")
        print(f" 組み合わせ数: {len(combinations)}")
        print(f" デフォルト枚数: {default_count}")
        print(f" 合計生成枚数: {total_images}")
        print(f"{'='*50}")

    def _run_generation_loop(self, p, jobs, total_images, skip_until,
                             original_prompt, initial_seed,
                             used_placeholders, active_slot_indices):
        all_images = []
        all_seeds = []
        all_prompts = []
        all_negative_prompts = []
        all_infotexts = []

        global_num = 0
        last_confirmed_num = skip_until
        interrupted = False

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

                self._print_progress_line(global_num, total_images, combo, j, count)

                replaced_prompt = self.build_prompt(
                    original_prompt, combo, used_placeholders, active_slot_indices
                )

                result = self._generate_one(
                    p, replaced_prompt, global_num, initial_seed,
                    last_confirmed_num, total_images,
                )
                if result is None:
                    interrupted = True
                    break

                self._collect_result(
                    p, result, replaced_prompt,
                    all_images, all_seeds, all_prompts,
                    all_negative_prompts, all_infotexts,
                )

                last_confirmed_num = global_num
                self._update_completed(last_confirmed_num)

                if global_num < total_images:
                    print("  VRAM解放中...")
                    self.free_vram()

        if not interrupted and last_confirmed_num >= total_images:
            self.mark_completed()

        status = "中断" if interrupted else "完了"
        print(f"\n{'='*50}")
        print(f" {status}: {len(all_images)}枚生成しました（全{total_images}枚中{last_confirmed_num}枚確認済み）")
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

    def _print_progress_line(self, global_num, total_images, combo, j, count):
        suffix = f" ({j+1}/{count})" if count > 1 else ""
        combo_display = " × ".join(
            (c[0][:20] + "...") if len(c[0]) > 20 else c[0]
            for c in combo
        )
        print(f"\n[{global_num}/{total_images}] {combo_display}{suffix} 生成中...")

    def _generate_one(self, p, replaced_prompt, global_num, initial_seed,
                      last_confirmed_num, total_images):
        """1枚生成。成功時は Processed を返し、停止すべき場合は None を返す。"""
        new_p = self.create_fresh_p(p, replaced_prompt)
        new_p.seed = -1 if initial_seed == -1 else initial_seed + (global_num - 1)

        try:
            try:
                result = process_images(new_p)
            except RuntimeError as e:
                self._print_fatal("✗", f"CUDAエラー: {e}")
                return None
            except Exception as e:
                self._print_fatal("✗", f"予期しないエラー: {e}")
                return None

            if shared.state.interrupted:
                print(f"\n⚡ 中断されました（{last_confirmed_num}/{total_images}枚完了）")
                return None

            if not result.images:
                self._print_fatal("⚠", "画像が生成されませんでした")
                return None

            return result
        finally:
            try:
                del new_p
            except Exception:
                pass

    def _print_fatal(self, mark, message):
        print(f"  {mark} {message}")
        print(f"  → 即停止します。再起動後に再開すればこの画像からリトライされます")

    def _collect_result(self, p, result, replaced_prompt, all_images, all_seeds,
                        all_prompts, all_negative_prompts, all_infotexts):
        all_images.extend(result.images)
        all_seeds.extend(result.all_seeds)
        all_prompts.append(replaced_prompt)
        all_negative_prompts.extend(result.all_negative_prompts)

        if getattr(result, 'infotexts', None):
            all_infotexts.extend(result.infotexts)
        else:
            seed_val = result.all_seeds[0] if result.all_seeds else -1
            all_infotexts.append(
                f"{replaced_prompt}\n"
                f"Negative prompt: {p.negative_prompt}\n"
                f"Steps: {p.steps}, Sampler: {p.sampler_name}, "
                f"CFG scale: {p.cfg_scale}, Seed: {seed_val}, "
                f"Size: {p.width}x{p.height}"
            )

        seed_text = result.all_seeds[0] if result.all_seeds else "不明"
        print(f"  ✓ 完了 (Seed: {seed_text})")
