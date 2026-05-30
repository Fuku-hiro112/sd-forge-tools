"""
api_endpoints.py - FastAPI エンドポイント登録モジュール

vram_safe_batch_v3b.py から抽出した FastAPI 登録ロジック。
script_callbacks.on_app_started(register_api) で呼び出す。

Phase 8-C2 以降: variables 系 API (sync_variables / variables / variables/events) と
file watcher は prompt_expander.py の register_variables_api へ移管済み。
本ファイルは pending_jobs 系 (set_jobs / status / peek_jobs) のみを担当する。
"""

import os

from . import pending_jobs

# API受信データの一時保存領域
_pending_data = {
    "group_list": None,
    "prompt": None,
    "negative_prompt": None,
    "timestamp": None,
}


def register_api(demo, app):
    """FastAPIエンドポイントを登録する（WebUI起動時に呼ばれる）.

    script_callbacks.on_app_started 用コールバック。
    pending_jobs 系 (set_jobs / status / peek_jobs) のみ登録。
    variables 系は prompt_expander.py の register_variables_api が担当。
    """
    import time
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware

    try:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception:
        pass

    @app.post("/vram_safe_batch/api/set_jobs")
    async def set_jobs(request: Request):
        try:
            body = await request.json()
            _pending_data["group_list"] = body.get("group_list", "")
            _pending_data["prompt"] = body.get("prompt")
            _pending_data["negative_prompt"] = body.get("negative_prompt")
            _pending_data["timestamp"] = time.strftime("%H:%M:%S")
            return JSONResponse({"status": "ok", "message": "データを受信しました"})
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

    @app.get("/vram_safe_batch/api/status")
    async def get_status():
        has_data = _pending_data["group_list"] is not None
        return JSONResponse({
            "has_pending_data": has_data,
            "timestamp": _pending_data.get("timestamp"),
        })

    @app.get("/vram_safe_batch/api/peek_jobs")
    async def peek_jobs():
        """§7: 受信データを取得し内部バッファをクリアする.

        Variable Manager → メインプロンプト textarea 流入のために JS から呼び出される。
        """
        payload = pending_jobs.consume_pending_jobs(_pending_data)
        if payload is None:
            return JSONResponse({"status": "empty", "message": "受信データがありません"})
        return JSONResponse({"status": "ok", **payload})

    print("[VRAM Safe Batch] pending-jobs API registered: /set_jobs /status /peek_jobs")
