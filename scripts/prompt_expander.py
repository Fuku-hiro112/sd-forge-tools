"""
prompt_expander.py - メインプロンプトの $変数 を AlwaysOn で展開する拡張

メインプロンプトに `$char` のような変数を書くと、vars/variables.json に登録した値で
展開され、複数枚生成される。dynamic-prompts と同じ AlwaysOn パターンで動作するため、
Batch Resume Script を選択していない通常生成でも変数展開が効く。

Phase 8-C2: variables 系 API (sync_variables / variables / variables/events) と
file watcher を api_endpoints.py から移管し、register_variables_api で登録する。

Phase 8-C-UI-1: ui() に展開順 UI / シードモード / 記法ガイド / 投入ボタンを追加
  (v3b 側はまだ削除しない - UI-1 は一時二重表示)

Phase 8-C-UI-3: _is_batch_resume_active ガードを撤去。
  batch_runner が resume 時は独自に履歴エントリから p を上書きするため、
  prompt_expander は常に p.all_prompts を populate する。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# ============================================================
#  Phase 8-D: vars/variables.json v1 → v2 自動 migration
#  (旧 v3b.py の起動時 migration ブロックを移管)
# ============================================================
try:
    from vram_safe_batch_modules import variables_store as _vs_for_migration
    _vmig_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "vars", "variables.json")
    )
    _vmig = _vs_for_migration.migrate_v1_to_v2_if_needed(_vmig_path)
    if _vmig:
        print(f"[Prompt Expander] variables.json を v2 形式へ移行: bak={_vmig}")
except Exception as e:
    print(f"[Prompt Expander] variables migration error: {e}")

import gradio as gr
from modules import scripts, script_callbacks
from vram_safe_batch_modules import expander, variables_store, pending_jobs
from vram_safe_batch_modules.ui_helpers import _normalize_df


def _detect_dynamic_prompts() -> bool:
    """sd-dynamic-prompts 拡張がインストールされているかを検出.

    `extensions/sd-dynamic-prompts` ディレクトリの存在で判定する。
    起動時に1回だけ呼ばれる。
    """
    try:
        repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        candidates = [
            os.path.join(repo_root, "extensions", "sd-dynamic-prompts"),
            os.path.join(repo_root, "extensions", "stable-diffusion-webui-prompt-all-in-one"),
        ]
        for path in candidates:
            if os.path.isdir(path):
                return True
        return False
    except Exception:
        return False


_DYNAMIC_PROMPTS_DETECTED = _detect_dynamic_prompts()

if _DYNAMIC_PROMPTS_DETECTED:
    print("[Prompt Expander] ⚠ 警告: sd-dynamic-prompts 拡張が検出されました。")
    print("[Prompt Expander]   両方とも `$varname` 構文を使用するため衝突する可能性があります。")
    print("[Prompt Expander]   一方を無効化することを推奨します。")


# === モジュールレベル状態 (variables SSE 用) ===
_change_subscribers: list = []          # list[asyncio.Queue]
_last_self_write_mtime: float = 0.0     # POST /sync_variables 書き込み直後の mtime
_VARS_WATCH_INTERVAL_SEC = 1.0


def _variables_path() -> str:
    """vars/variables.json への絶対パスを返す.

    __file__ = scripts/prompt_expander.py
    → .. → リポジトリルート
    """
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "vars", "variables.json")
    )


def register_variables_api(demo, app):
    """variables 系 API + SSE + file watcher を FastAPI に登録.

    script_callbacks.on_app_started 用コールバック。
    以下のエンドポイントを登録する:
      POST /vram_safe_batch/api/sync_variables
      GET  /vram_safe_batch/api/variables
      GET  /vram_safe_batch/api/variables/events
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse, StreamingResponse
    from fastapi.middleware.cors import CORSMiddleware

    try:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception:
        pass  # api_endpoints が既に登録済みの場合は無視

    @app.post("/vram_safe_batch/api/sync_variables")
    async def sync_variables(request: Request):
        """Variable Manager → vars/variables.json 同期 (Phase A: replace のみ).

        Body: {"mode": "replace", "categories": [...]}
        """
        try:
            body = await request.json()
        except Exception as e:
            return JSONResponse({"status": "error", "message": f"invalid JSON: {e}"}, status_code=400)

        mode = body.get("mode", "replace")
        categories = body.get("categories", [])

        if mode != "replace":
            return JSONResponse(
                {"status": "error", "message": f"Phase A は mode='replace' のみ対応 (got {mode!r})"},
                status_code=400,
            )
        if not isinstance(categories, list):
            return JSONResponse(
                {"status": "error", "message": "'categories' must be a list"},
                status_code=400,
            )

        try:
            bak = variables_store.save_variables_v2(_variables_path(), categories)
            n = sum(1 for _ in variables_store.walk_variables(categories))
            # Phase B: SSE の自己ループ抑止用に書き込み直後の mtime を記録
            global _last_self_write_mtime
            try:
                _last_self_write_mtime = os.path.getmtime(_variables_path())
            except OSError:
                pass
            return JSONResponse({
                "status": "ok",
                "variables_written": n,
                "backup": bak,
            })
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    @app.get("/vram_safe_batch/api/variables")
    async def get_variables():
        """vars/variables.json の現在の v2 ツリーを返す (Manager 起動時取り込み用)."""
        try:
            return JSONResponse(variables_store.load_raw_v2(_variables_path()))
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    @app.get("/vram_safe_batch/api/variables/events")
    async def variables_events(request: Request):
        """Phase B: vars/variables.json の変更を SSE で push 通知.

        Manager 側で `new EventSource(...)` で購読し、外部エディタによる手動編集を
        リアルタイムで反映できるようにする。
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        _change_subscribers.append(queue)

        async def event_stream():
            try:
                # 接続直後に hello イベント（クライアント側初期化用）
                yield "event: ready\ndata: {}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    except asyncio.TimeoutError:
                        # keep-alive ping
                        yield ": ping\n\n"
                        continue
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            finally:
                if queue in _change_subscribers:
                    _change_subscribers.remove(queue)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # Phase B: vars/variables.json の mtime を polling して変更を SSE 購読者に push.
    async def _watch_variables_file():
        global _last_self_write_mtime
        last_known = 0.0
        path = _variables_path()
        try:
            last_known = os.path.getmtime(path) if os.path.isfile(path) else 0.0
        except OSError:
            pass
        _last_self_write_mtime = last_known
        while True:
            try:
                cur = os.path.getmtime(path) if os.path.isfile(path) else 0.0
            except OSError:
                cur = 0.0
            if cur != last_known and cur != _last_self_write_mtime and _change_subscribers:
                payload = {"type": "external_change", "mtime": cur}
                for q in list(_change_subscribers):
                    try:
                        q.put_nowait(payload)
                    except asyncio.QueueFull:
                        pass
            last_known = cur
            await asyncio.sleep(_VARS_WATCH_INTERVAL_SEC)

    # register_variables_api は同期コールバックなので、ここで asyncio.create_task を直接呼ぶと
    # "RuntimeError: no running event loop" になる。FastAPI startup イベントを使って
    # uvicorn の event loop が立ち上がった直後にタスクを生成する。
    @app.on_event("startup")
    async def _start_variables_watcher():
        asyncio.create_task(_watch_variables_file())

    print("[Prompt Expander] variables API registered: /sync_variables /variables /variables/events")


# 起動時に script_callbacks へ登録
script_callbacks.on_app_started(register_variables_api)


class PromptExpander(scripts.Script):
    sorting_priority = 5  # dynamic-prompts より前で実行する想定 (要 L2 確認)

    def title(self):
        return "$ Prompt Expander"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, *args, **kwargs):
        # is_img2img を取得 (Forge は kwargs か positional で渡す)
        is_img2img = args[0] if args else kwargs.get("is_img2img", False)
        tab_suffix = "img2img" if is_img2img else "txt2img"
        base_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

        def _vars_path():
            return os.path.join(base_dir, "vars", "variables.json")

        with gr.Accordion("$ Prompt Expander", open=False):
            # === 既存: 説明 Markdown + dynamic-prompts 警告 + enabled checkbox ===
            gr.Markdown(
                "メインプロンプトに `$char` のように変数を書くと、`vars/variables.json` から値を展開して複数枚生成します。\n\n"
                "- 通常生成 (Script 未選択) でも有効\n"
                "- **Batch Resume Script 選択時は本拡張は自動で無効**になり、Batch Resume 側の展開が優先されます\n"
                "- dynamic-prompts と共存させると衝突する可能性があります"
            )
            if _DYNAMIC_PROMPTS_DETECTED:
                gr.Markdown(
                    "<div style='background:rgba(217,119,6,0.12);border-left:4px solid #d97706;"
                    "padding:10px 12px;color:#f5b042;border-radius:2px;'>"
                    "⚠ <strong style='color:#fbbf24;'>sd-dynamic-prompts</strong> "
                    "<span style='color:#f5b042;'>拡張が検出されました。両者とも</span> "
                    "<code style='background:rgba(217,119,6,0.22);color:#fde68a;padding:1px 6px;"
                    "border-radius:3px;font-family:monospace;'>$varname</code> "
                    "<span style='color:#f5b042;'>構文を使用するため衝突する可能性があります。"
                    "一方を無効化することを推奨します。</span>"
                    "</div>"
                )
            enabled = gr.Checkbox(
                label="変数展開を有効化",
                value=True,
                info="OFF にすると本拡張は何もしません",
            )

            # === 新規: 記法・使い方 Accordion ===
            with gr.Accordion("📖 記法・使い方", open=False):
                with gr.Accordion("① 変数参照の書き方", open=False):
                    gr.Markdown(
                        "メインプロンプトに `$名前` をそのまま書くと展開対象になります。\n\n"
                        "**例**\n"
                        "```\n"
                        "masterpiece, $キャラ, $mood, best quality\n"
                        "```\n"
                    )

                with gr.Accordion("② 変数名に使える文字 / 使えない文字", open=False):
                    gr.Markdown(
                        "| 位置 | 使える文字 |\n"
                        "|---|---|\n"
                        "| 先頭 1 文字 | 英字 / ひらがな / カタカナ / 漢字 / `_`（**数字は不可**）|\n"
                        "| 2 文字目以降 | 上記 + 数字 + `(` `)` `:` `、`（全角カンマ）|\n\n"
                        "**使えない文字（区切り扱い）**: 半角スペース / 改行 / `=` / `;` / `,`（半角カンマ）/ `$`\n\n"
                        "**有効な名前の例**\n"
                        "- `$char` `$キャラ` `$ポケモンキャラ2`\n"
                        "- `$ナンジャモ(ジム:雷)`\n"
                        "- `$アイリス(ジム:ドラゴン、四天王:BW)`\n\n"
                        "**最長一致ルール**: `$foo` と `$foo(bar)` の両方が定義済みなら、本文の `$foo(bar)` は長い方が優先されます。\n"
                    )

                with gr.Accordion("③ 変数定義の 3 方式", open=False):
                    gr.Markdown(
                        "**A. ブロック定義（推奨）**\n\n"
                        "`変数---` と `---` で囲んだ範囲に、`$名前 = 値;値;値` を 1 行で書く形式。\n"
                        "```\n"
                        "変数---\n"
                        "$キャラ = alice;bob;carol\n"
                        "$服   = 制服;私服\n"
                        "---\n"
                        "```\n\n"
                        "**B. 複数行値（ブロック内のみ）**\n\n"
                        "値が多いときは `$名前=` だけ書いて改行し、続く行に 1 つずつ並べ `;` で区切る。\n"
                        "次の `$名前=` 行か `---` で値の蓄積を確定します。\n"
                        "```\n"
                        "変数---\n"
                        "$キャラ=\n"
                        "alice;\n"
                        "bob;\n"
                        "carol\n"
                        "---\n"
                        "```\n"
                        "値は別の変数参照でも OK（多段展開されます）。\n"
                        "```\n"
                        "$ポケモンキャラ2=\n"
                        "$チリ(SV:四天王);\n"
                        "$ミモザ(保険の先生)\n"
                        "```\n\n"
                        "**C. インライン定義（ブロック外）**\n\n"
                        "行頭に `$名前 = 値;値` を 1 行で書く。複数行値は使えません。\n"
                    )

                with gr.Accordion("④ 優先順位 / 展開順", open=False):
                    gr.Markdown(
                        "**定義の優先順位**\n\n"
                        "インライン / ブロック定義 　＞　 `vars/variables.json`\n\n"
                        "**展開順**\n"
                        "- 「📊 展開順」リストの **上が外側ループ**（変化が遅い）、**下が内側ループ**（先に全パターン回る）\n"
                        "- 空のままなら本文の出現順で自動展開\n"
                    )

                with gr.Accordion("⑤ 値の高度な記法", open=False):
                    gr.Markdown(
                        "- **`;`** … alternation（OR 選択肢）\n"
                        "- **`$別の変数`** を値に書くと多段展開（最大 12 段、循環は自動停止）\n"
                        "- **`//x;y//`** … インラインスロット（スロット内 alternation）\n"
                    )

                with gr.Accordion("⑥ 廃止記法", open=False):
                    gr.Markdown(
                        "- 旧 `{1}{2}` 記法は廃止。検出時は警告ログのみ出力。\n"
                    )

                with gr.Accordion("⑦ シードモード（固定 / 連番）", open=False):
                    gr.Markdown(
                        "**連番（デフォルト）**\n"
                        "- 1 枚目: `initial_seed`、2 枚目: `initial_seed + 1`、... と +1 ずつ\n"
                        "- バリエーション生成・既定の使い方\n\n"
                        "**固定**\n"
                        "- 全画像で同じ `initial_seed` を使う\n"
                        "- プロンプトや LoRA だけ変えて **構図を保ったまま比較** したいとき\n\n"
                        "**`Seed = -1` の挙動**\n"
                        "- 開始時に **1 回だけ** 乱択して固定値に解決\n"
                        "- その値を連番/固定のロジックに使う（生成列が再現可能になる）\n\n"
                        "**履歴と再開**\n"
                        "- `seed_mode` と解決後シード `resolved_initial_seed` を履歴保存\n"
                        "- 再開すると同じシード列で続行される\n"
                    )

                with gr.Accordion("⑧ ネガティブプロンプト自動展開", open=False):
                    gr.Markdown(
                        "**仕組み**\n"
                        "- Variable Manager で各変数に `negative` 値を設定できる\n"
                        "- メインプロンプト本体に `$foo` を書くと、対応する `foo.negative` がネガティブプロンプト末尾に自動追加される\n\n"
                        "**例**\n"
                        "Manager で `$char = positive: \"1girl, alice\" / negative: \"bad anatomy, low quality\"` を定義したとき:\n"
                        "```\n"
                        "メインプロンプト   : $char, masterpiece\n"
                        "ネガティブプロンプト: text\n"
                        "↓ 生成時に展開\n"
                        "Positive : 1girl, alice, masterpiece\n"
                        "Negative : text, bad anatomy, low quality\n"
                        "```\n\n"
                        "**ルール**\n"
                        "- メインプロンプトに直接書かれた `$foo` のみ対象（多段展開の中間変数は対象外）\n"
                        "- インライン定義 `$x = ...` の変数は negative フィールドを持たないため対象外\n"
                        "- 同じ negative 文字列が元のネガティブに既にあれば重複追加しない\n"
                    )

            # === 新規: 展開順 UI ===
            df_elem_id = f"vsb_expansion_order_{tab_suffix}"
            up_elem_id = f"vsb_btn_up_{tab_suffix}"
            down_elem_id = f"vsb_btn_down_{tab_suffix}"
            remove_elem_id = f"vsb_btn_remove_{tab_suffix}"

            gr.Markdown(
                "**📊 展開順** — 上が外側ループ / クリック選択 → `Alt+↑↓` 並び替え / `Delete` 削除"
            )

            expansion_order_df = gr.Dataframe(
                value=[],
                headers=["変数名"],
                datatype=["str"],
                row_count=(1, "dynamic"),
                col_count=(1, "fixed"),
                type="array",
                interactive=True,
                elem_id=df_elem_id,
                show_label=False,
            )

            selected_row_state = gr.State(0)

            with gr.Row():
                btn_move_up = gr.Button("▲", elem_id=up_elem_id, scale=0, min_width=44)
                btn_move_down = gr.Button("▼", elem_id=down_elem_id, scale=0, min_width=44)
                btn_remove_row = gr.Button("×", elem_id=remove_elem_id, scale=0, min_width=44)
                btn_clear_order = gr.Button("⟲", scale=0, min_width=44)
                add_var_input = gr.Textbox(
                    placeholder="変数名を入力 → ➕",
                    show_label=False,
                    scale=3,
                    container=False,
                )
                btn_add_var = gr.Button("➕", scale=0, min_width=44)

            with gr.Row():
                btn_refresh_from_main = gr.Button(
                    "🔄 メインから取得", scale=2, variant="primary"
                )
                btn_refresh_preview = gr.Button("🔢 枚数プレビュー", scale=2)
                expansion_preview = gr.Textbox(
                    placeholder="プレビュー",
                    value="",
                    interactive=False,
                    lines=1,
                    scale=3,
                    show_label=False,
                    container=False,
                )

            # === 新規: シードモード Radio ===
            seed_mode_radio = gr.Radio(
                choices=[
                    ("連番（バリエーション生成）", "sequential"),
                    ("固定（構図維持してプロンプト比較）", "fixed"),
                ],
                value="sequential",
                label="🎲 シードモード",
                info="連番: seed=N から +1 ずつ。固定: 全画像で同じ seed。seed=-1 のときは開始時に 1 回だけ乱択して以降は固定/連番ロジックを適用。",
            )

            # === 新規: Variable Manager → メインプロンプト投入 ===
            with gr.Row():
                api_load_btn = gr.Button(
                    "📥 Variable Manager → メイン Prompt に投入",
                    scale=2,
                    variant="secondary",
                )
                api_status = gr.Textbox(
                    placeholder="ステータス",
                    value="",
                    interactive=False,
                    lines=1,
                    scale=3,
                    show_label=False,
                    container=False,
                )

            # === イベントハンドラ ===

            # 行選択の追跡
            def on_row_select(evt: gr.SelectData):
                if evt.index is None:
                    return 0
                return evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index

            expansion_order_df.select(
                fn=on_row_select, inputs=[], outputs=[selected_row_state]
            )

            # 上へ
            def on_move_up(data, idx):
                data = _normalize_df(data)
                if idx is None or idx <= 0 or idx >= len(data):
                    return data, idx if idx is not None else 0
                data[idx - 1], data[idx] = data[idx], data[idx - 1]
                return data, idx - 1

            btn_move_up.click(
                fn=on_move_up,
                inputs=[expansion_order_df, selected_row_state],
                outputs=[expansion_order_df, selected_row_state],
            )

            # 下へ
            def on_move_down(data, idx):
                data = _normalize_df(data)
                if idx is None or idx < 0 or idx >= len(data) - 1:
                    return data, idx if idx is not None else 0
                data[idx], data[idx + 1] = data[idx + 1], data[idx]
                return data, idx + 1

            btn_move_down.click(
                fn=on_move_down,
                inputs=[expansion_order_df, selected_row_state],
                outputs=[expansion_order_df, selected_row_state],
            )

            # 削除
            def on_remove_row(data, idx):
                data = _normalize_df(data)
                if idx is None or idx < 0 or idx >= len(data):
                    return data, idx if idx is not None else 0
                data.pop(idx)
                new_idx = min(idx, len(data) - 1) if data else 0
                return data, new_idx

            btn_remove_row.click(
                fn=on_remove_row,
                inputs=[expansion_order_df, selected_row_state],
                outputs=[expansion_order_df, selected_row_state],
            )

            # クリア
            def on_clear_order():
                return [], 0

            btn_clear_order.click(
                fn=on_clear_order,
                inputs=[],
                outputs=[expansion_order_df, selected_row_state],
            )

            # 追加
            def on_add_var(data, name):
                data = _normalize_df(data)
                name = (name or "").strip().lstrip("$").strip()
                if not name:
                    return data, ""
                existing = {row[0] for row in data if row}
                if name in existing:
                    return data, ""
                data.append([name])
                return data, ""

            btn_add_var.click(
                fn=on_add_var,
                inputs=[expansion_order_df, add_var_input],
                outputs=[expansion_order_df, add_var_input],
            )
            add_var_input.submit(
                fn=on_add_var,
                inputs=[expansion_order_df, add_var_input],
                outputs=[expansion_order_df, add_var_input],
            )

            # メインプロンプトから取得（JS で textarea を読み取って Python に渡す）
            hidden_main_prompt_holder = gr.Textbox(visible=False)

            def on_refresh_from_main(main_prompt_text):
                if not main_prompt_text:
                    return [], "メインプロンプトが空です"
                try:
                    parsed = expander.parse_main_prompt(main_prompt_text)
                    json_vars = variables_store.load_variables(_vars_path())
                    merged = expander.merge_variables(parsed.inline_vars, json_vars)
                    used = expander.extract_used_variables(parsed.body, merged)
                    if not used:
                        return [], "メインプロンプトに $変数 が見つかりません"
                    rows = [[v] for v in used]
                    return rows, f"メインプロンプトから {len(used)} 個の変数を取得"
                except Exception as e:
                    return [], f"⚠ 解析エラー: {e}"

            btn_refresh_from_main.click(
                fn=on_refresh_from_main,
                js=(
                    "() => {"
                    f" const id = '{tab_suffix}_prompt';"
                    " const ta = document.querySelector('#' + id + ' textarea');"
                    " return [ta ? ta.value : ''];"
                    "}"
                ),
                inputs=[hidden_main_prompt_holder],
                outputs=[expansion_order_df, expansion_preview],
            )

            # 生成枚数プレビュー（メインプロンプト + 展開順から計算）
            def on_refresh_preview(main_prompt_text, df_data):
                try:
                    if not main_prompt_text:
                        return "メインプロンプトが空です"
                    parsed = expander.parse_main_prompt(main_prompt_text)
                    json_vars = variables_store.load_variables(_vars_path())
                    merged = expander.merge_variables(parsed.inline_vars, json_vars)
                    rows = _normalize_df(df_data)
                    order = [row[0] for row in rows if row and row[0]]
                    expanded = expander.expand_prompts(parsed.body, merged, order)
                    n = len(expanded)
                    msg = f"🔢 {n} 枚生成される予定"
                    if parsed.has_legacy_n_notation:
                        msg += "  ⚠ 旧 {N} 記法を検出"
                    return msg
                except Exception as e:
                    return f"⚠ 解析エラー: {e}"

            btn_refresh_preview.click(
                fn=on_refresh_preview,
                js=(
                    "(holder, df) => {"
                    f" const id = '{tab_suffix}_prompt';"
                    " const ta = document.querySelector('#' + id + ' textarea');"
                    " return [ta ? ta.value : '', df];"
                    "}"
                ),
                inputs=[hidden_main_prompt_holder, expansion_order_df],
                outputs=[expansion_preview],
            )

            # Variable Manager → メインプロンプト投入ボタン
            hidden_api_status_holder = gr.Textbox(visible=False)
            api_load_btn.click(
                fn=lambda msg: msg or "",
                inputs=[hidden_api_status_holder],
                outputs=[api_status],
                js=(
                    "async () => {"
                    f" const tabId = '{tab_suffix}_prompt';"
                    "  try {"
                    "    const r = await fetch('/vram_safe_batch/api/peek_jobs');"
                    "    if (!r.ok) return ['✗ サーバ応答エラー (' + r.status + ')'];"
                    "    const data = await r.json();"
                    "    if (data.status !== 'ok') return ['受信データなし。Variable Manager から送信してください。'];"
                    "    const ta = document.querySelector('#' + tabId + ' textarea');"
                    "    if (!ta) return ['✗ textarea が見つかりません: #' + tabId];"
                    "    const text = data.group_list || '';"
                    "    ta.value = text;"
                    "    ta.dispatchEvent(new Event('input', { bubbles: true }));"
                    "    const preview = text.slice(0, 60).replace(/\\n/g, ' ');"
                    "    return ['✓ ' + (data.timestamp || '') + ' 投入: ' + preview + (text.length > 60 ? '…' : '')];"
                    "  } catch (e) {"
                    "    return ['✗ エラー: ' + e.message];"
                    "  }"
                    "}"
                ),
            )

        # script_args 順序: enabled, expansion_order_df, seed_mode_radio
        return [enabled, expansion_order_df, seed_mode_radio]

    def process(self, p, *args, **kwargs):
        """AlwaysOn 展開: p.prompt を変数展開して p.all_prompts を書換.

        batch_runner (再開モード) は独自に履歴エントリから p.all_prompts を上書きするため、
        prompt_expander は常に展開処理を行う。

        script_args 順序: enabled, expansion_order_df, seed_mode_radio
        """
        enabled = bool(args[0]) if len(args) >= 1 else False
        expansion_order_df = args[1] if len(args) >= 2 else []
        seed_mode = args[2] if len(args) >= 3 else "sequential"

        if not enabled:
            return

        main_prompt = getattr(p, "prompt", None) or ""
        if not main_prompt:
            return

        # 展開
        try:
            parsed = expander.parse_main_prompt(main_prompt)
            if not parsed.body:
                return
            json_vars = variables_store.load_variables(_variables_path())
            merged = expander.merge_variables(parsed.inline_vars, json_vars)

            # UI の Dataframe 値があればそれを使い、無ければ auto-order
            rows = _normalize_df(expansion_order_df)
            ui_order = [row[0] for row in rows if row and row[0]]
            if ui_order:
                order = [name for name in ui_order if name in merged]
                # UI に書いてあるが辞書に無い名前は警告だけ出して落とす
                missing = [name for name in ui_order if name not in merged]
                if missing:
                    print(f"[Prompt Expander] ⚠ 展開順 UI 内の未定義変数を無視: {missing}")
            else:
                # auto-order: 本文出現順
                used = expander.extract_used_variables(parsed.body, merged)
                order = [v for v in used if v in merged]

            if not order:
                # 変数参照無し or 辞書に未定義 → 展開不要
                return
            expanded = expander.expand_prompts(parsed.body, merged, order)
        except Exception as e:
            print(f"[Prompt Expander] expansion failed: {e}")
            return

        if not expanded or len(expanded) <= 1:
            # 1 枚分しか無いなら標準パスに任せる
            return

        # p に展開結果を流し込む (dynamic-prompts と同パターン)
        n = len(expanded)
        p.all_prompts = expanded
        base_negative = getattr(p, "negative_prompt", "") or ""

        # ネガティブ自動展開 (Phase 8-C4)
        try:
            negative_dict = variables_store.load_negative_dict(_variables_path())
        except Exception:
            negative_dict = {}
        try:
            neg_additions = expander.collect_negative_additions(parsed.body, merged, negative_dict)
            effective_negative = expander.compose_negative_prompt(base_negative, neg_additions)
            if neg_additions:
                print(f"[Prompt Expander] ネガティブ自動追加: {neg_additions}")
        except Exception as e:
            print(f"[Prompt Expander] negative expansion failed: {e}")
            effective_negative = base_negative

        p.all_negative_prompts = [effective_negative] * n

        # シードモード
        if seed_mode not in ("fixed", "sequential"):
            seed_mode = "sequential"

        base_seed = getattr(p, "seed", -1)
        if base_seed == -1 or base_seed is None:
            # seed -1 のときは Forge が各 iter で乱択する。-1 のままリストにする。
            p.all_seeds = [-1] * n
            p.all_subseeds = [-1] * n
        elif seed_mode == "fixed":
            # 全画像同じシード
            p.all_seeds = [int(base_seed)] * n
            p.all_subseeds = [int(getattr(p, "subseed", 0) or 0)] * n
        else:  # sequential
            p.all_seeds = [int(base_seed) + i for i in range(n)]
            p.all_subseeds = [int(getattr(p, "subseed", 0) or 0) + i for i in range(n)]
        p.n_iter = n
        p.batch_size = 1

        # batch_runner が参照できるよう order / seed_mode を stash
        p._pe_expansion_order = order
        p._pe_seed_mode = seed_mode

        print(f"[Prompt Expander] $変数展開: {n} プロンプトに展開 (順序={order}, seed_mode={seed_mode})")
