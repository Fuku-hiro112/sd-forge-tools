"""
image_generator.py - 画像生成処理モジュール

1枚ずつVRAMを解放しながら生成する処理を担当。
エラー時は即停止し、進捗は成功確認後にのみ更新する（ロールバック対応）。
"""

import copy

import modules.shared as shared
from modules.processing import process_images
from . import vram_manager


def create_fresh_p(original_p, new_prompt, new_negative=None):
    """元の p をシャローコピーしてプロンプトのみ差し替えた新しい p オブジェクトを作る.

    `copy.copy(original_p)` で scripts / script_args / extra_generation_params /
    styles / hr_* / subseed* / override_settings 等を全部引き継ぐ。
    これにより ADetailer / sd-forge-couple など alwayson 拡張の各種フック
    （before_process / process_batch / postprocess_image 等）が正しく起動される。

    new_negative が指定された場合、そのネガティブプロンプトを使用する。
    未指定の場合は original_p のネガティブプロンプトをそのまま引き継ぐ。
    """
    new_p = copy.copy(original_p)
    new_p.prompt = new_prompt
    if new_negative is not None:
        new_p.negative_prompt = new_negative
    new_p.batch_size = 1
    new_p.n_iter = 1
    new_p.do_not_save_samples = False
    new_p.do_not_save_grid = True
    # 前イテレーションの transient state（プロンプト conditioning / イテレーション番号 / 結果リスト）
    # を初期化しておかないと、process_images 内で前回のリストに追記される or 不整合になる。
    new_p.all_prompts = None
    new_p.all_negative_prompts = None
    new_p.all_seeds = None
    new_p.all_subseeds = None
    new_p.prompts = None
    new_p.negative_prompts = None
    new_p.seeds = None
    new_p.subseeds = None
    new_p.iteration = 0
    new_p.extra_result_images = []
    return new_p


def generate_one(p, replaced_prompt, seed, replaced_negative=None):
    """1枚生成する。
    
    Args:
        p: 元のprocessingオブジェクト
        replaced_prompt: 置換済みポジティブプロンプト
        seed: シード値
        replaced_negative: 置換済みネガティブプロンプト（Noneの場合はpのネガティブを使用）
    
    Returns:
        (success, result, interrupted)
        success: 生成成功かどうか
        result: 生成結果（失敗時はNone）
        interrupted: Interruptボタンで中断されたかどうか
    """
    new_p = create_fresh_p(p, replaced_prompt, replaced_negative)
    new_p.seed = seed

    try:
        result = process_images(new_p)

        # 生成後にInterrupt検知
        if shared.state.interrupted:
            # Interruptの場合、結果があれば成功扱い
            if result.images and len(result.images) > 0:
                return True, result, True
            return False, None, True

        # 画像が正常に生成されたか確認
        if result.images and len(result.images) > 0:
            return True, result, False
        else:
            print(f"  ⚠ 画像が生成されませんでした")
            print(f"  → 即停止します。再起動後に再開すればこの画像からリトライされます")
            return False, None, True

    except RuntimeError as e:
        print(f"  ✗ CUDAエラー: {e}")
        print(f"  → 即停止します。再起動後に再開すればこの画像からリトライされます")
        return False, None, True
    except Exception as e:
        print(f"  ✗ 予期しないエラー: {e}")
        print(f"  → 即停止します。再起動後に再開すればこの画像からリトライされます")
        return False, None, True
    finally:
        try:
            del new_p
        except Exception:
            pass


def collect_result(result, replaced_prompt, p, all_images, all_seeds,
                   all_prompts, all_negative_prompts, all_infotexts):
    """生成結果を収集リストに追加する"""
    all_images.extend(result.images)
    all_seeds.extend(result.all_seeds)
    all_prompts.append(replaced_prompt)
    all_negative_prompts.extend(result.all_negative_prompts)

    if hasattr(result, 'infotexts') and result.infotexts:
        all_infotexts.extend(result.infotexts)
    else:
        seed_val = result.all_seeds[0] if result.all_seeds else -1
        info = (
            f"{replaced_prompt}\n"
            f"Negative prompt: {p.negative_prompt}\n"
            f"Steps: {p.steps}, Sampler: {p.sampler_name}, "
            f"CFG scale: {p.cfg_scale}, Seed: {seed_val}, "
            f"Size: {p.width}x{p.height}"
        )
        all_infotexts.append(info)

    seed_text = result.all_seeds[0] if result.all_seeds else "不明"
    print(f"  ✓ 完了 (Seed: {seed_text})")
