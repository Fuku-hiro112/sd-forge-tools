# vram_safe_batch 改修サマリ（実装計画）

**最終更新:** 2026-05-22
**対象スコープ:** `scripts/vram_safe_batch_v3b.py` および `scripts/vram_safe_batch_modules/`
**対象外:** `vram_safe_batch.py` (v3 / 旧), `vram_safe_batch_v3a.py`
**前提:** dynamic-prompts は OFF で運用（共存は遠い将来の別案件）

## 実装順序

1. §1 メインプロンプト統合（基盤、最優先）
2. §2 シード値モード
3. §3 completed カウンタのタイミング
4. §4 履歴ドロップダウン乖離
5. §6 UI コンパクト化
6. §7 「Forge に送信」フロー
7. §5 不在 LoRA【ペンディング、実害が出るまで実装しない】
8. §8 責務分離 Phase 2【§1〜§7 完了後】

各セクションは独立して実装・テスト・動作確認できる単位。`feature/<kebab-case>` ブランチで個別に進める。

---

## §1 メインプロンプト統合（確定仕様）

### BEFORE（問題）

vram_safe_batch v3b は専用 `gr.Textbox(label="生成リスト")` に `$変数 = ...` や `//` を書く方式。生成順とプロンプト内位置（優先度）を `{N}` 記法でリンクさせるが、対応関係が直感的でなく可読性が低い。

例:
```
メイン: {3}{1}{2}
vramsafe: 1girl // $服装変数 // $キャラ
```

**問題点:**
- tagcomplete は `#txt2img_prompt` 限定 → 専用 textbox では効かない
- ADetailer / Hires.fix 他拡張との連携が分かりにくい
- `{1}{2}{3}` の対応を頭で組み直す必要があり可読性が低い
- 共通変数を別プロンプトで再利用できず、毎回書き直し

### AFTER（確定仕様）

#### 1-A. 変数名直接埋め込み + ドラッグ並び替え展開順

- メイン Prompt に `$char, 1girl, $outfit` のように **変数名を位置で直接書く**。プロンプト内位置 = SD 優先度がそのまま見える
- 展開順（ループのネスト順）は vram_safe_batch UI 側の **ドラッグ並び替えリスト** で指定。上が外側ループ（変化が遅い）

#### 1-A-2. メイン内変数定義の記法

- **ブロック**: `変数---` と `---` で囲まれた範囲を変数定義として認識
- **インライン**: ブロック外でも行頭 `$名前 = ...` 行は変数定義として扱う
- 優先順位: **メイン内定義 > `variables.json`**

#### 1-B. `{N}` 記法は完全廃止

- パーサーは `{N}` を読まない。検出時は警告ログのみ
- 旧 `batch_history.json` はマイグレーションせず `.bak.{timestamp}` にリネームして破棄

#### 1-C. 外部変数ファイル `vars/variables.json`

- 1 ファイル集中、JSON 形式（schema v1）。起動時に全自動読込（`@use` 不要）
- `sd_variable_manager.html` から直接編集（カテゴリ・タグ・並び替え）

#### 1-D. history 形式刷新（schema v2）

- `extensions` / `prompt.main` / `expansion_order` / `used_variables` 等を保存
- 将来 Phase 2 の責務分離後も互換確認可能

### 入力例

**例1: variables.json に全部置く**
```
$char, 1girl, $outfit, best quality
```

**例2: ブロックで局所定義**
```
変数---
$char = alice;bob
$outfit = casual;formal
---
$char, 1girl, $outfit, best quality
```

**例3: インラインで局所定義**
```
$extra = smile;serious
$char, 1girl, $outfit, $extra, best quality
```

**展開順 UI（ドラッグ並び替え）:**
```
① $char    ← 外側ループ（変化が遅い）
② $outfit  ← 内側ループ（先に全パターン回る）
```

**variables.json サンプル:**
```json
{
  "schema_version": 1,
  "variables": [
    {"name": "char",   "category": "characters", "values": ["alice", "bob"]},
    {"name": "outfit", "category": "outfits",    "values": ["casual", "formal"]}
  ]
}
```

**出力（生成プロンプト 4 通り）:**
```
alice, 1girl, casual, best quality
alice, 1girl, formal, best quality
bob,   1girl, casual, best quality
bob,   1girl, formal, best quality
```

**history v2 サンプル:**
```json
{
  "schema_version": 2,
  "entries": [{
    "id": "20260520-091533-a1b2",
    "timestamp": "2026-05-20 09:15:33",
    "extensions": {"vram_safe_batch": "3b.2.0"},
    "prompt": {
      "main": "$char, 1girl, $outfit, best quality",
      "negative": "...",
      "expansion_order": ["char", "outfit"],
      "used_variables": {"char": ["alice","bob"], "outfit": ["casual","formal"]}
    },
    "generation": {"width": 1024, "height": 1024, "cfg_scale": 7, "steps": 28,
                   "sampler": "...", "scheduler": "...", "seed_mode": "...",
                   "initial_seed": 12345, "clip_skip": 2},
    "progress": {"completed": 5, "total": 16, "status": "running"}
  }]
}
```

### 留意点

- dynamic-prompts と同時 ON だと `$varname=` で pyparsing 例外。OFF 前提で開発
- 本体プロンプトに装飾用の `---` を書くとブロック終了タグと誤認するため、ブロック記法使用時は本体に裸の `---` を含めない
- 展開順 UI は Gradio のドラッグ並び替えコンポーネント次第。実装上の制約がある場合は上下移動ボタンで暫定対応

### 影響範囲

- **新規**:
  - `scripts/vram_safe_batch_modules/variables_store.py`
  - `scripts/vram_safe_batch_modules/expander.py`
  - `scripts/vram_safe_batch_modules/history_v2.py`
  - `vars/variables.json`
  - `tests/test_variables_store.py`
  - `tests/test_expander.py`
  - `tests/test_history_v2.py`
- **改修**: `scripts/vram_safe_batch_v3b.py`, `scripts/sd_variable_manager.html`
- **リネーム**: `batch_history.json` → `batch_history.json.bak.{timestamp}`

---

## §2 シード値モード（固定 / 連番）

### BEFORE

シードは `initial_seed + (global_num - 1)` の **連番固定**。同一画像を量産する「固定」モードが選べなかった。

### AFTER

`gr.Radio` で 2 択:

- **固定**: 全画像で `seed = initial_seed`（構図維持してプロンプト/LoRA 比較用）
- **連番**: 現行通り `initial_seed + (global_num - 1)`（デフォルト、バリエーション生成用）

`initial_seed = -1` 指定時は開始シードを WebUI 側で乱択 → 以降は連番で続行。これにより「毎回違うバリエーション群」が表現でき、純粋ランダムの用途を吸収する。

シード計算は純粋関数 `compute_seed(mode, initial_seed, global_num)` に切り出して単体テスト可能化。

### 「ランダム」モード廃止の理由

SD のシード→画像写像はカオス的で、`seed=N` と `seed=N+1` の出力は事実上無相関。連番モードでも視覚的にはランダム同等のバリエーションが得られるため、独立した「ランダム」モードは連番モードに完全に吸収される。再現性も連番の方が優れる（同じ `initial_seed` で同じ画像列を再生成可能）。

履歴に `seed_mode` と `resolved_initial_seed`（`-1` 解決後の実値）を保存し、resume 時に同じモード・同じシード列で継続。

### 影響範囲

- `scripts/vram_safe_batch_v3b.py`（UI に Radio 追加、loop 内のシード計算置換）
- `scripts/vram_safe_batch_modules/progress.py`（`compute_seed` 追加、`create_new_progress` に `seed_mode` 引数）
- `tests/test_compute_seed.py`（新規）

---

## §3 completed カウンタの更新タイミング

### BEFORE

画像生成が中断 (`is_interrupted=True`) されても、`generate_one()` が部分結果を返してきた場合は `update_completed` が呼ばれて `completed` がバンプされる。

結果: 途中再開すると、中断時に半端だった画像番号がスキップされて **1 枚抜け** る（ファイル名の番号に歯抜けが発生）。

### AFTER

純粋関数 `should_update_completed(success, is_interrupted) -> bool` を追加し、**中断時はバンプしない**ルールに変更。中断後 resume すれば同じ画像番号から再生成する。

### 留意点

WebUI の `postprocess_image` フック方式に移行すれば、画像が確実に保存された後にしか発火しないので、より自然に同じ意味が実現できる（将来検討）。

### 影響範囲

- `scripts/vram_safe_batch_modules/progress.py`（`should_update_completed` 追加）
- `scripts/vram_safe_batch_v3b.py`（generate ループ内の判定置換）
- `tests/test_should_update_completed.py`（新規）

---

## §4 履歴ドロップダウンの乖離

### BEFORE

履歴ドロップダウン `history_dropdown` の `choices` は Forge 起動時に `ui()` で 1 回だけ計算される。生成中・生成終了で `batch_history.json` が更新されてもドロップダウンには反映されない。

結果: ドロップダウン表示と「詳細」テキストボックスの内容が **乖離** する。

### AFTER

`history_dropdown.focus` イベントを紐付け、**ドロップダウンを開こうとした瞬間** に `get_dropdown_choices(base_dir)` を呼び直して `gr.update(choices=..., value=...)` を返す。手動ボタンは追加しない。

現在選択中の value は可能なら維持（新 choices に含まれていれば）、含まれていなければ先頭にフォールバック。choices 変化に伴い既存の `change` ハンドラが連鎖し、詳細テキストボックスも自動追随する。

### ポーリング不採用の根拠

`batch_history.json` の更新タイミングは生成完了・中断・クラッシュ後起動に限定され、外部から不規則に変わるファイルではない。Timer ポーリングはアイドル時負荷を生むだけで利得がない。focus イベント駆動なら「履歴を選びたい瞬間」に必ず最新で、アイドル時オーバーヘッドゼロ。

純粋ロジックは `compute_focus_update(current_value, new_choices) -> (choices, value)` として切り出し単体テスト可能化。

### 影響範囲

- `scripts/vram_safe_batch_v3b.py::ui()`（`history_dropdown.focus` ハンドラ追加）
- `scripts/vram_safe_batch_modules/progress.py`（`compute_focus_update` 追加）
- `tests/test_history_dropdown_focus.py`（新規）

---

## §5 不在 LoRA クラッシュ回避【ペンディング】

**ステータス:** ペンディング（2026-05-21 判断）。ユーザーは LoRA ファイルを削除しない運用のため、現状では本問題は発生しない。実害が出た時点で実装する。

**詳細計画:** `~/.claude/plans/3-jaunty-pike.md` に保存済み。

### 問題の概要（参考）

プロンプトに `<lora:NAME:WEIGHT>` があり、NAME が `models/Lora/` に存在しないと:
- `extensions-builtin/sd_forge_lora/networks.py:63` で `network_on_disk.filename` が `AttributeError`
- except 節も同じ `.filename` を参照していて二次クラッシュ（Forge 側のバグ）

### 再開判断のトリガー

- LoRA ファイルを整理・削除した
- 過去 `batch_history.json` を resume したら不在 LoRA で落ちた
- メインプロンプトに古い `<lora:...>` が混入してクラッシュした
- Forge 本家が修正 PR をマージしてバージョンアップで取り込めた → 本計画は不要になる（要確認）

---

## §6 UI コンパクト化（VSCode 風検索＋全要素）

### BEFORE

v3b セクションが縦に長く、スクロールが多い。さらに専用 textbox が tagcomplete や他拡張と分断されている:

- 上部の使い方説明 Markdown（4行）が常時展開
- 履歴セクション（ドロップダウン + 6行詳細 + チェックボックス）が常時展開
- 置換ツールが常時5行占有（検索/置換ボックス、オプション、マッチ情報、5ボタン）。しかも対象が **v3b 専用 textbox 限定** でメインプロンプトに使えない
- 生成リスト textbox が `lines=100`（画面の大半を占める）— §1 で完全廃止が決まっている
- カラープレビュー HTML が生成リストと同等の高さで常時表示 — §1 廃止対象の textbox に追随するので一緒に廃止
- 記法ヘルプ Markdown（5行）と「プレビュー」見出し Markdown（2行）が縦に積まれる
- 変数管理アプリ連携が「読み込み」「挿入」の 2 ボタンに分散

### AFTER

#### ① 生成リスト textbox とカラープレビュー HTML は完全廃止（§1 整合）

- 専用 textbox は削除。ユーザーは `#txt2img_prompt` / `#img2img_prompt` のメインプロンプト欄に変数記法（`$char, 1girl, $outfit`）を直接書く
- カラープレビュー HTML も廃止（メインプロンプト欄に対する別領域のプレビューは表示位置がずれて使いにくいため）
- 変数定義のシンタックスハイライトが欲しくなったら、メインプロンプト textarea を `MutationObserver` で監視して上にオーバーレイ表示する方式を将来検討

#### ② 置換ツールを VSCode 風フローティングパネル化（対象はメインプロンプト欄）

- `gr.Group(elem_id="vsb-search-panel")` + カスタム CSS で **メインプロンプト欄の右上** に `position: absolute` 配置
- カスタム JS で **メインプロンプト欄にフォーカスがある状態で** `Ctrl+F` 押下時にパネル表示トグル、`Esc` で閉じる
- マッチ件数を `3 / 12` 形式で表示、`▲▼` ジャンプ時は `#txt2img_prompt textarea` の該当文字を `setSelectionRange` で **選択状態** にして可視化
- 「置換」「一括置換」「Undo」は既存ロジック（`text_tools.py`）を流用しつつ、入出力対象をメインプロンプト textarea に切り替え

#### ③ 説明・ヘルプの折りたたみ

- 上部の使い方 Markdown と「生成リスト」記法ヘルプを統合して `gr.Accordion("📖 記法・使い方", open=False)` に格納
- 記法サンプル（変数定義ブロック、インライン定義、展開順 UI 説明など）も同 Accordion 内に集約

#### ④ 既存計画の継続

- 「途中再開」を `gr.Accordion(open=False)` で折りたたみ
- 変数管理アプリ連携は「📥 Variable Manager → メイン Prompt に投入」1 ボタンに統合

### VSCode 風検索の対象が「メインプロンプト」になることの含意

- v3b 単独機能ではなく WebUI 全体への被せ機能になる → AlwaysOn 化前提なら自然な拡張
- txt2img と img2img の両タブでメインプロンプトを対象にする（それぞれの elem_id を見て切替）
- Forge 標準の Ctrl+F（ブラウザのページ内検索）と衝突するため、**フォーカスがメインプロンプト textarea にある時のみ** 横取りする実装が必要

### 実装段階

- **段階A（本フェーズで実装）**: フローティングパネル + Ctrl+F トグル + 選択ハイライトで代替。実装工数最小
- **段階B（将来検討）**: 黄色背景の真のハイライト。textarea 上に同期する透明オーバーレイを JS で重ねる方式

### 影響範囲

- `scripts/vram_safe_batch_v3b.py::ui()`（生成リスト textbox とプレビュー HTML 削除、Accordion 化、フローティングパネル定義、Ctrl+F バインド JS 埋め込み）
- `scripts/vram_safe_batch_modules/text_tools.py`（置換ロジックをメインプロンプト textarea 対象に変換、マッチ件数 `N / M` 形式の整形関数を純粋関数化）
- 削除: `generate_preview_html` 関連の参照

---

## §7 「Forge に送信」フロー

### BEFORE

変数管理アプリ `sd_variable_manager.html` から「Forge に送信」を押すと `POST /vram_safe_batch/api/set_jobs` が呼ばれ、サーバ側の `_pending_data` に保存される。ユーザーは Forge タブに切り替えて「📥 読み込み」ボタンを押し、Python ハンドラ経由で v3b の生成リスト textbox に展開する必要があった（タブ切替 + 2クリック）。

§1 でメインプロンプト統合・生成リスト textbox 廃止が決まったため、この流入経路は **そのままでは行き場を失う**。流入先をメインプロンプト textarea に切り替える必要がある。

### AFTER

新 API `GET /vram_safe_batch/api/peek_jobs` を追加（取得 + 内部バッファクリア）。Variable Manager から送信されたデータは JS 経由で **メインプロンプト textarea に直接流し込む**:

- txt2img タブなら `#txt2img_prompt textarea`
- img2img タブなら `#img2img_prompt textarea`
- 書き込み後 `input` イベントを `dispatchEvent` して Gradio に値変化を通知

Forge 側 UI のボタンは「📥 Variable Manager → メイン Prompt に投入」1 ボタンに統合（§6 ④と整合）。ボタン押下時に `peek_jobs` を叩いて取得し、上記 textarea へ書き込む。

### 留意点

- 既存 `POST /set_jobs` エンドポイントは互換のため残す。Variable Manager 側の `forge.js` は変更不要
- 古い Python 側「📥 読み込み」ハンドラ `on_api_load`（v3b 専用 textbox に書き込んでいたもの）は削除
- Variable Manager 側で送信するペイロードは現状の `group_list / prompt / negative_prompt` を維持。流入先側で `group_list` を main prompt にマッピングする（命名整理は Phase 2 で）

### 影響範囲

- `scripts/vram_safe_batch_v3b.py::_register_api()`（`peek_jobs` 追加）
- `scripts/vram_safe_batch_v3b.py::ui()`（ボタンと JS。古い `on_api_load` 削除）
- 互換維持: `scripts/sd_variable_manager.html`（変更不要）

---

## §8 責務分離（Phase 2 案）【§1〜§7 完了後】

`vram_safe_batch` という名前に反して、現状 1 つのスクリプトが 5 つの責務を抱えている。Phase 2 で機能別に独立拡張へ分割する案:

- **prompt_expander**: `$変数 / // / ; / {N}` 展開（`job_builder_a/b.py` ベース）
- **vram_recycler**: 各画像生成後の VRAM 解放（`vram_manager.py` ベース）
- **batch_resume**: 履歴・途中再開（`progress.py` ベース）
- **text_replace**: 文字置換ツール（メインプロンプト対象に再設計）

各拡張は `scripts.Script` または `script_callbacks` で独立登録、相互依存最小化。

### 着手条件

- §1〜§7 の Phase 1 で機能が安定してから着手
- `scripts/` 直下に副作用コードを置かない（CLAUDE.md ルール）→ サブモジュールは `scripts/{ext}_modules/` へ

### 影響範囲

- `scripts/{prompt_expander,vram_recycler,batch_resume,text_replace}.py`（いずれも新規）
- 対応する `{ext}_modules/`

---

## 実装時の共通ルール

### CLAUDE.md ルールの遵守

- **scripts/ 直下に副作用コードを置かない**: WebUI が起動時に全 `.py` を auto-import するため、副作用コードは webui.bat 起動不能化を招く
- テストは `tests/` 配下に配置、`sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))` で import パスを通す
- ファイル移動時は `scripts/__pycache__/` の対応 `.pyc` も削除

### Git Flow

- 実装作業前に `feature/<kebab-case>` ブランチを作成
- main / develop に直接コミットしない
- ターン終了時の自動 commit、セッション終了時の develop マージは Hook 任せ

### TDD（tdd-forge skill）

- Pre-flight → RED → GREEN → REFACTOR → VERIFY
- 純粋関数（`compute_seed`, `should_update_completed`, `compute_focus_update` 等）は L1 ユニットテストで担保
- UI 改修（§6, §7）は L2（ブラウザ操作）で動作確認
- GPU 実行を伴う変更（§1 全体）は L3 で CUDA フォールバックがないことを確認

---

## 保留事項（後日対応）

### Pending-1: ADetailer + Hires.fix + v3b 併用時の「同じ画像 2 枚」問題

**ステータス:** §2 完了時点で未着手（2026-05-23 保留判断）

**症状:**
ADetailer ON + Hires.fix ON + VRAM Safe Batch v3b の 3 点併用時、
**1 プロンプトあたり同じ画像が 2 枚生成される**。

**経緯:**
直前の修正で `scripts/vram_safe_batch_modules/image_generator.py` の `create_fresh_p` を
`copy.copy(original_p)` ベースに書き換え、ADetailer / sd-forge-couple 等 alwayson 拡張が
初めて動作するようになった。それ以前は ADetailer 自体が起動していなかったため本症状は表面化していなかった。

**原因仮説（コード読みで絞り込み済み、確定未）:**

| 候補 | 該当オプション / コード位置 | 発生条件 |
|---|---|---|
| (A) mask の result.images 追加 | `modules/processing.py:1100-1113` の `output_images.append(image_mask)` / `image_mask_composite` 経路 | `opts.return_mask` または `opts.return_mask_composite` が True、かつ ADetailer 由来の `mask_for_overlay` が outer p に伝播している場合 |
| (B) ADetailer の "save before image" | `extensions/adetailer/scripts/!adetailer.py:919-921` の `self.save_image(... "-ad-before")` | ADetailer 設定 `ad_save_images_before` が True（disk のみ、gallery には来ない）|
| (C) Hires.fix 前画像の追加保存 | `modules/processing.py:1441-1448` の `save_intermediate` | WebUI 設定 `save_images_before_highres_fix` が True（disk のみ、gallery には来ない）|
| (D) その他 | - | gallery 重複なら別経路、disk 重複なら B/C |

`v3b` の `collect_result` は `result.images` を 1 件しか extend しないため、gallery の重複は (A) 経路が最も疑わしい。

**推奨アプローチ:**
コードを推測修正する前に診断ログを入れて発生箇所を確定させる。

```python
# scripts/vram_safe_batch_modules/image_generator.py の generate_one() 末尾
print(f"[v3b-debug] result.images={len(result.images)}, "
      f"extra_images={len(getattr(result, 'extra_images', []))}, "
      f"infotexts={len(result.infotexts) if result.infotexts else 0}")

# scripts/vram_safe_batch_v3b.py の _run_internal() ループ初回 1 度だけ
if global_num == skip_until + 1:
    from modules.shared import opts
    print(f"[v3b-debug] return_mask={getattr(opts, 'return_mask', '?')}, "
          f"return_mask_composite={getattr(opts, 'return_mask_composite', '?')}, "
          f"save_images_before_highres_fix={getattr(opts, 'save_images_before_highres_fix', '?')}, "
          f"ad_save_images_before={opts.data.get('ad_save_images_before', '?')}")
```

**修正方針（経路確定後）:**

- (A) の場合: v3b の new_p で `return_mask` / `return_mask_composite` を強制 False にオーバーライド、または `collect_result` で `result.images[:1]` のみ extend
- (B) の場合: コード修正不要、ユーザーに ADetailer の "Save before image" を OFF にする設定案内をドキュメント化
- (C) の場合: 同様にユーザー設定 OFF 案内のみ

**再開判断のトリガー:**
ユーザーから「ADetailer + Hires.fix + v3b の 2 枚問題が業務に支障」との報告があった時点。
それまでは ADetailer / Hires.fix のいずれかを OFF にする運用回避で対応。

---

### Pending-2: §6 ② 置換ツールのフローティングパネル化（VSCode 風 Ctrl+F）

**ステータス:** 未着手（2026-05-24 保留判断）

**スコープ:**

- `gr.Group(elem_id="vsb-search-panel")` + CSS で main prompt 欄右上に `position: absolute` 配置
- `Ctrl+F` トグル JS、`Esc` 閉じる JS（main prompt textarea にフォーカスがあるときのみ横取り）
- マッチ件数 `N / M` 表示、`▲▼` ジャンプ時に `setSelectionRange` でハイライト
- 置換 / 一括置換 / Undo（既存 `text_tools.py` の `replace_one` / `replace_all` を流用）

**ペンディング理由:**
WebUI の `<script>` 注入は `script_callbacks.on_app_started` ベースの static asset 注入が必要で実装工数が大きい。
展開順 UI 縮小・§7・§8 を先行し、まとめて着手するほうが効率的。

**Cleanup（先行して着手可、本件着手まで先送りでも可）:**

- `scripts/vram_safe_batch_modules/text_tools.py` から未使用となった `generate_preview_html` / `_colorize_line` / `_colorize_main` / `_escape_html` / `COLORS` を削除
- 置換系関数（`find_matches` / `replace_one` / `replace_all` / `navigate_match` / `get_match_info`）は §6 ② 着手まで保持

---

## 追加実施事項

### §7 完了（2026-05-24）

**実装内容:**

- 新規 API `GET /vram_safe_batch/api/peek_jobs` を `_register_api` に追加。`_pending_data` を読み取り内部バッファをクリアした上で `{status, group_list, prompt, negative_prompt, timestamp}` を返す
- 純粋関数 `consume_pending_jobs(pending) -> Optional[dict]` を新モジュール `scripts/vram_safe_batch_modules/pending_jobs.py` に切り出し
- UI ボタンを「📥 Variable Manager → メイン Prompt に投入」に統合（旧「Variable Managerから読込（情報表示のみ）」を置換）
- ボタン click は JS のみで完結:
  1. `/vram_safe_batch/api/peek_jobs` を fetch
  2. レスポンスの `group_list` を該当タブの `#txt2img_prompt textarea` または `#img2img_prompt textarea` に書き込み
  3. `input` イベントを `dispatchEvent` して Gradio に値変化を通知
  4. ステータス文字列を返してボタン右の Textbox に表示
- Python 側の旧ハンドラ `on_api_load`（v3b 専用 textbox 用）は削除
- `POST /set_jobs` / `GET /status` は互換のため維持（Variable Manager 側 `forge.js` は変更不要）

**ファイル変更:**

- 追加: `scripts/vram_safe_batch_modules/pending_jobs.py`
- 変更: `scripts/vram_safe_batch_v3b.py`（API 1 個追加、UI ボタンラベルと JS、import 1 行追加、旧ハンドラ削除）
- 追加: `tests/test_pending_jobs.py`（5 ケース、99 テスト全件パス）

**使用感への影響:**

| 項目 | 修正前 | 修正後 |
|---|---|---|
| Variable Manager 送信 → Forge 反映 | タブ切替 + 「📥 読込」ボタン押下 + 情報表示のみ（main prompt には入らない） | 「📥 投入」ボタン 1 クリックでメインプロンプト欄に直接反映 |
| 操作回数 | 2 クリック以上 + 手動コピペ | 1 クリック |
| 反映先 | v3b 専用 textbox（§1 で廃止済み）| `#txt2img_prompt` / `#img2img_prompt` textarea |
| ステータス表示 | 情報文字列のみ | 投入結果プレビュー（最初の 60 文字）|

**留意点:**

- JS が動かないブラウザでは反映できない（現実的にはほぼないが、フォールバックなし）
- Variable Manager 側 ペイロードは現状の `group_list / prompt / negative_prompt` 維持。流入先で `group_list` を main prompt にマッピング（命名整理は §8 / Phase 2 で）

---

### §6 ①③④ 完了（2026-05-24）

- ① 生成リスト textbox / カラープレビュー HTML 廃止 → §1 で完了済み
- ③ 上部使い方 Markdown を `📖 記法・使い方` Accordion 化済み（7 サブセクション構成）
- ④ 「途中再開」を `📂 途中再開` Accordion 化済み、Variable Manager 連携ボタンは 1 ボタンに整理済み

### 展開順 UI 縮小化（2026-05-24、§6 ② 代替の優先タスク）

**Context:**
v3b の「📊 展開順」セクションが縦に 7 ブロック (~400px) 占有しメインプロンプト欄を圧迫していた。
§6 ② フローティングパネル化が工数大でペンディングのため、より即時効果の高い本タスクを優先実施。

**BEFORE → AFTER:**

| 構成 | 行数 |
|---|---|
| BEFORE（見出し / 説明 / Dataframe / 並び替えボタン行 / 追加行 / 取得+プレビュー行 / プレビュー欄） | 7 ブロック |
| AFTER（見出し兼説明 / Dataframe / 並び替え+追加 1 行統合 / 取得+プレビュー+プレビュー欄 1 行統合） | 4 ブロック |

**主な縮小手段:**

- 見出し `### 📊 展開順` と説明 Markdown 2 ブロックを 1 行の **太字 + ヒント** に統合
- 並び替えボタン（▲▼×⟲）を 1 文字アイコン化、`scale=0, min_width=44` で正方形気味に並べ「追加」入力欄も同一行へ
- 「🔄 メインから取得」「🔢 枚数プレビュー」とプレビュー Textbox を 1 行に詰め、`container=False` + `show_label=False` で余白削減
- Dataframe は `label="展開順"` を消し（見出しに統合）→ `show_label=False`

**影響範囲:**

- 変更: `scripts/vram_safe_batch_v3b.py`（`ui()` 内、400-444 行付近のみ。約 44 行 → 約 30 行）
- イベントハンドラ / 変数名 / elem_id は完全に維持。ロジック・テストへの影響なし

**使用感への影響:**

| 項目 | 修正前 | 修正後 |
|---|---|---|
| 展開順セクション縦幅 | 7 ブロック (~400px) | 4 ブロック (~200px) |
| メインプロンプト欄との視界距離 | 遠い | 近い |
| ボタンラベル | 「▲ 上へ」等 文字付き | 「▲」等 アイコンのみ |
| プレビュー Textbox | `label="プレビュー"` ラベル付き | placeholder で兼用、行内 |

**確認事項（L2）:**

- ▲▼×⟲ ➕ のボタン挙動が変わらないこと
- 🔄 メインから取得 → Dataframe 更新 → 🔢 枚数プレビュー → プレビュー欄表示 のフローが壊れていないこと
- `Alt+↑↓` 並び替え・`Delete` 削除のショートカット動作不変
