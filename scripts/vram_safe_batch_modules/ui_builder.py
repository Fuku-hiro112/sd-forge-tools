"""
ui_builder.py - VRAMSafeBatchV3B の UI 構築を担当するモジュール (Phase 8-C-UI-4 縮小)

履歴・再開 UI のみを構築する。
展開順 / シードモード / 記法ヘルプ / 各ボタンは prompt_expander へ移管済み。
"""

import gradio as gr

from . import history_v2, progress
from .ui_helpers import (
    _history_choices,
    _entry_detail,
    _parse_dropdown_index,
)


def build_ui(is_img2img: bool, base_dir: str) -> list:
    """v3b の UI を構築し、return すべきコンポーネントのリストを返す.

    Args:
        is_img2img: scripts.Script.ui() に渡される is_img2img
        base_dir: リポジトリルート絶対パス (履歴ファイルの引き元)

    Returns:
        [history_dropdown, resume_check]
    """
    gr.Markdown("## Batch Resume — 履歴と再開")

    # ==========================================
    #  履歴・再開セクション
    # ==========================================
    with gr.Accordion("📂 途中再開", open=False):
        choices = _history_choices(base_dir)
        history_dropdown = gr.Dropdown(
            choices=choices,
            label="再開する履歴を選択",
            value=choices[0] if choices else None,
            info="中断した履歴を選択して続きから再開（最大5件保持）",
        )

        history_detail = gr.Textbox(
            label="選択中の履歴詳細",
            value=_entry_detail(base_dir, 0),
            interactive=False,
            lines=5,
        )

        resume_check = gr.Checkbox(
            label="選択した履歴から再開する",
            value=False,
            info="チェックONの場合、入力欄の設定は無視され選択した履歴の設定が使われます",
        )

        def on_dropdown_change(choice):
            idx = _parse_dropdown_index(choice)
            return _entry_detail(base_dir, idx) if idx >= 0 else ""

        history_dropdown.change(
            fn=on_dropdown_change,
            inputs=[history_dropdown],
            outputs=[history_detail],
        )

        # ドロップダウンを開こうとした瞬間に choices を再計算
        def on_dropdown_focus(current_value):
            fresh = _history_choices(base_dir)
            new_choices, new_value = progress.compute_focus_update(current_value, fresh)
            return gr.update(choices=new_choices, value=new_value)

        history_dropdown.focus(
            fn=on_dropdown_focus,
            inputs=[history_dropdown],
            outputs=[history_dropdown],
        )

    return [history_dropdown, resume_check]
