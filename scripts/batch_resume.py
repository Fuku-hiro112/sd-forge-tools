"""
batch_resume.py - Batch Resume (履歴・中断再開専用 Script)

【概要】
メインプロンプトに $変数 を直接埋め込んで、変数定義を展開しながらバッチ生成する。
履歴の保存・途中再開機能を担当する専用 Script。

【使い方】
1. WebUI で普段通りプロンプト・設定を行う
2. メインプロンプトに `$char, 1girl, $outfit, best quality` のように変数名を直接書く
3. 変数定義は以下のいずれかで:
   - `vars/variables.json` に登録する（永続）
   - メインプロンプト内で `変数--- $char = alice;bob ---` ブロック定義
   - メインプロンプト内で行頭 `$char = alice;bob` インライン定義
   - 優先度: インライン/ブロック定義 > variables.json
4. Script ドロップダウンから「Batch Resume」を選択
5. 「📊 展開順」テキストエリアに展開する変数名を1行ずつ書く（上が外側=変化が遅い）
   - 「🔄 メインプロンプトから取得」で自動入力
6. Generate

【展開例】
   メイン: $char, 1girl, $outfit, best quality
   $char = alice;bob, $outfit = casual;formal, 展開順 = [char, outfit]
   → 4プロンプト生成:
       1. alice, 1girl, casual, best quality
       2. alice, 1girl, formal, best quality
       3. bob,   1girl, casual, best quality
       4. bob,   1girl, formal, best quality

【途中再開】
   中断後、ドロップダウンで履歴を選択 → 「選択した履歴から再開」にチェック → Generate
"""

import os
import sys

# モジュールパスを追加（vram_safe_batch_modulesはscripts/フォルダ内に配置）
sys.path.insert(0, os.path.dirname(__file__))

import modules.scripts as scripts
from modules.processing import process_images
from modules import script_callbacks

from vram_safe_batch_modules import history_v2


# 再帰防止フラグ
_running = False


def _repo_root() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


# ========================================================
#  起動時マイグレーション: 旧 batch_history.json を .bak へ
# ========================================================
try:
    _migrated = history_v2.migrate_legacy_if_needed(_repo_root())
    if _migrated:
        print(f"[Batch Resume] 旧履歴をバックアップしました: {_migrated}")
except Exception as e:
    print(f"[Batch Resume] migration error: {e}")


from vram_safe_batch_modules.api_endpoints import register_api
script_callbacks.on_app_started(register_api)


class BatchResume(scripts.Script):

    def title(self):
        return "Batch Resume"

    def show(self, is_img2img):
        return True

    def ui(self, is_img2img):
        from vram_safe_batch_modules.ui_builder import build_ui
        return build_ui(is_img2img, _repo_root())

    def run(self, p, history_dropdown, resume_check):
        global _running
        if _running:
            return process_images(p)
        _running = True
        try:
            return self._run_internal(p, history_dropdown, resume_check)
        finally:
            _running = False

    def _run_internal(self, p, history_dropdown, resume_check):
        from vram_safe_batch_modules.batch_runner import run_batch
        return run_batch(p, history_dropdown, resume_check, repo_root=_repo_root())
