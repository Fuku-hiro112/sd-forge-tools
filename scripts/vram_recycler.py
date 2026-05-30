"""
vram_recycler.py - 画像生成ごとに VRAM を解放する AlwaysOn 拡張

UI トグル (デフォルト OFF) で有効化すると、各画像生成後に GPU メモリを解放する。
v3b の生成ループ専用だった処理を独立化し、Forge 標準バッチや X/Y/Z plot でも利用可能にした。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import gradio as gr
from modules import scripts
from vram_safe_batch_modules import vram_manager


class VRAMRecycler(scripts.Script):
    sorting_priority = 19  # neveroom (18) の直後

    def title(self):
        return "VRAM Recycler"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, *args, **kwargs):
        with gr.Accordion("🧹 VRAM Recycler", open=False):
            enabled = gr.Checkbox(
                label="画像ごとに VRAM を解放",
                value=False,
                info="各画像生成後に torch.cuda.empty_cache() / gc.collect() を実行します。複数枚生成で VRAM が溜まる環境向け (デフォルト OFF)。",
            )
        return [enabled]

    def postprocess_image(self, p, pp, *args, **kwargs):
        # script_args は (enabled,) を渡す約束
        enabled = bool(args[0]) if args else False
        if enabled:
            print("[VRAM Recycler] 画像生成後の VRAM 解放中...")
            vram_manager.free_vram()
