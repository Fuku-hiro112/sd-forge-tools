"""
vram_manager.py - VRAM・モデル管理モジュール
"""

import gc
import torch


def free_vram():
    """VRAMキャッシュを解放する"""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    gc.collect()


def reload_model():
    """モデルをアンロード→リロードしてキャッシュを完全クリア
    再開時のテンソルサイズ不一致エラーを防止するために使用"""
    try:
        import modules.sd_models as sd_models
        print("  モデルキャッシュをクリア中...")
        sd_models.unload_model_weights()
        sd_models.reload_model_weights()
        free_vram()
        print("  モデルキャッシュクリア完了")
    except Exception as e:
        print(f"  ⚠ モデルリロードエラー（続行します）: {e}")
        free_vram()
