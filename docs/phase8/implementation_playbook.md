# §8 責務分離 — Claude 実装プレイブック

> このファイルは **Claude (実装エージェント) が見ながら実装する用途**。
> ユーザー向けの要約は `docs/phase8/refactoring_plan.html` 参照。

## ゴール

`scripts/vram_safe_batch_v3b.py` (1075 行モノリス) を 4 つの独立 Forge 拡張に分割する。
**動作不変が最優先**。下表の機能一覧の挙動が Phase 完了ごとに全て維持されていることを毎回検証する。

---

## 現状機能一覧 (Inventory) ― 全段階で維持

### A. UI 機能

| ID | 機能 | 現状の場所 | Phase 移管先 |
|---|---|---|---|
| UI-01 | Script 名「VRAM Safe Batch v3b [メインプロンプト統合]」が Script ドロップダウンに出る | v3b.py `title()` | 8-D で「Batch Resume」にリネーム |
| UI-02 | 📖 記法・使い方 Accordion (8 サブセクション ①〜⑧) | v3b.py `ui()` | 8-A で `ui_builder.py` に移動 |
| UI-03 | 📂 途中再開 Accordion (履歴ドロップダウン + 詳細 + チェック) | v3b.py `ui()` | 8-A → 8-D で `batch_resume.py` |
| UI-04 | 履歴ドロップダウン focus 時の choices 動的再計算 (§4) | v3b.py + progress.py | 8-D に維持 |
| UI-05 | 履歴選択 → 詳細 Textbox 連動 | v3b.py | 8-D |
| UI-06 | 「📊 展開順」見出し + 操作ヒント文 | v3b.py | 8-D |
| UI-07 | 展開順 Dataframe (行 dynamic, 1 列, 編集可) | v3b.py | 8-D |
| UI-08 | 行クリック選択ハイライト (`selected_row_state`) | v3b.py | 8-D |
| UI-09 | ▲▼×⟲ ボタンで並び替え・削除・クリア | v3b.py | 8-D |
| UI-10 | 「➕」追加ボタン + 入力 textbox (重複検出付き) | v3b.py | 8-D |
| UI-11 | 「🔄 メインから取得」ボタン (JS で textarea 読み取り + 変数抽出) | v3b.py | 8-D (or 8-C 連携) |
| UI-12 | 「🔢 枚数プレビュー」ボタン | v3b.py | 8-D |
| UI-13 | プレビュー Textbox (1 行、container=False) | v3b.py | 8-D |
| UI-14 | 🎲 シードモード Radio (連番/固定) | v3b.py | 8-D |
| UI-15 | 「📥 Variable Manager → メイン Prompt に投入」ボタン | v3b.py | 8-C へ移管 |
| UI-16 | ステータス表示 Textbox (peek_jobs 結果) | v3b.py + hidden_api_status_holder | 8-C |

### B. 生成ループ機能 — I/O コントラクト (TDD 必須)

> ⚠ **重要**: ここに記載した関数の **input/output シグネチャと挙動は仕様の正本**。
> Phase 8 の各タスクで、これらを変更してはならない。変更が必要な場合は **必ずユーザーに確認**して許可を取ること。
> 全ての関数について「先にテストで I/O 契約を確認 → 実装は触らない」を徹底する。

#### GEN-01: `expander.parse_main_prompt(text: str) -> ParseResult`

| 項目 | 仕様 |
|---|---|
| **入力** | `text: str` (メインプロンプト全体) |
| **出力** | `ParseResult(body: str, inline_vars: dict[str, list[str]], has_legacy_n_notation: bool)` |
| **挙動** | `変数---` 〜 `---` ブロック解析、行頭 `$x = a;b` インライン定義抽出、複数行値定義対応 |
| **副作用** | なし (純粋関数) |
| **テスト** | `tests/test_expander.py::ParseMainPromptTests` (8 ケース), `MultiLineBlockValueTests` (4 ケース) |
| **不変条件** | inline_vars の値リストは元の順序保持、空 alt はスキップ |

#### GEN-02 〜 GEN-03: インライン/複数行値定義 (GEN-01 と同一関数で扱う)

#### GEN-04: `expander.extract_used_variables(body: str, variables: dict[str, list[str]] | None = None) -> list[str]`

| 項目 | 仕様 |
|---|---|
| **入力** | `body: str`, `variables: dict | None` |
| **出力** | `list[str]` (出現順、重複排除) |
| **挙動** | variables 渡されたら**辞書キーで最長一致**抽出、無ければ正規表現ベース(word のみ) |
| **副作用** | なし |
| **テスト** | `ExtractUsedVariablesTests` (4), `ExtractUsedVariablesWithDictTests` (2), `SpecialCharVariableNameTests` (5) |
| **不変条件** | variables 渡しの場合、辞書に無い名前は返らない |

#### GEN-05 〜 GEN-06: カンマ補完 / inline slot (GEN-07 expand_prompts 内部実装)

#### GEN-07: `expander.expand_prompts(body: str, variables: dict[str, list[str]], expansion_order: list[str]) -> list[str]`

| 項目 | 仕様 |
|---|---|
| **入力** | `body: str`, `variables: dict[name → list[positive_value]]`, `expansion_order: list[name]` |
| **出力** | `list[str]` (展開後プロンプト全件) |
| **挙動** | スロット直積 → 各 template に変数置換 → 値内の `;`/`//` は再評価 → 最大 12 段の多段展開 |
| **副作用** | なし |
| **テスト** | `ExpandPromptsTests`, `NestedExpansionTests`, `SlotAlternationTests`, `CommaAutoInsertionTests`, `RecursiveValueExpansionTests`, `AutoExpandReachableTests`, `SpecialCharVariableNameTests` (合計約 30 ケース) |
| **不変条件** | order が空でも自動展開、`{N}` 記法検出は警告のみ、循環は `_MAX_NESTED_DEPTH = 12` で停止 |

#### GEN-08: 循環参照停止 (GEN-07 内部、`_MAX_NESTED_DEPTH = 12`)

#### GEN-09: `variables_store.load_variables(vars_path: str) -> dict[str, list[str]]`

| 項目 | 仕様 |
|---|---|
| **入力** | `vars_path: str` (絶対パス) |
| **出力** | `dict[name → list[positive_value]]` (flat) |
| **挙動** | v1 / v2 schema 自動判別、v2 ツリーは walk して flat 化 |
| **副作用** | なし (読み取りのみ) |
| **テスト** | `LoadVariablesTests` (8), `LoadVariablesV2Tests` (5) |
| **不変条件** | ファイル無 / 破損 / 非対応 schema → 空 dict (例外を投げない) |

#### GEN-10: `_strip_dollar_prefix(name)` 自動適用 (Hotfix-1)

| 項目 | 仕様 |
|---|---|
| **挙動** | `_load_v2_positive_flat` / `load_negative_dict` で name 先頭 `$` を strip |
| **理由** | Variable Manager は `$char` 形式で保存、expander は `$` 抜きで照合 |
| **テスト** | `test_v2_load_strips_dollar_prefix_in_name`, `test_load_negative_dict_strips_dollar_prefix` |
| **不変条件** | 冪等 (`$` 無しの name はそのまま返す) |

#### GEN-11: `_normalize_value(s)` 自動適用 (Hotfix-2)

| 項目 | 仕様 |
|---|---|
| **挙動** | `_load_v2_positive_flat` / `load_negative_dict` で値の前後の空白と `;` を strip |
| **理由** | Manager は値末尾に `;` を付ける慣習。substitute 後の本文と連結時に spurious alt 分裂を防ぐ |
| **テスト** | `test_v2_load_strips_trailing_semicolon_from_value`, `test_v2_load_strips_leading_and_trailing_whitespace_and_semicolons`, `test_v2_load_preserves_internal_semicolons` |
| **不変条件** | **内部の `;` は保持** (alt 区切りとして機能) |

#### GEN-12: シードモード解決 (resolve_initial_seed)

`progress.resolve_initial_seed(initial_seed) -> int`

| 項目 | 仕様 |
|---|---|
| **入力** | `initial_seed: int | None` (-1 or None 含む) |
| **出力** | `int` (>= 0) |
| **挙動** | -1 / None → `secrets.randbelow(2**32 - 1)` で乱択、それ以外はそのまま |
| **副作用** | なし |
| **テスト** | `ResolveInitialSeedTests` (4 ケース) |

#### GEN-13: `progress.compute_seed(mode: str, initial_seed: int, global_num: int) -> int`

| 項目 | 仕様 |
|---|---|
| **入力** | `mode: "fixed" | "sequential"`, `initial_seed: int >= 0`, `global_num: int >= 1` |
| **出力** | `int` (画像のシード値) |
| **挙動** | `fixed`: initial_seed そのまま / `sequential`: initial_seed + (global_num - 1) |
| **副作用** | なし |
| **エラー** | `initial_seed < 0` または `mode` 不明で `ValueError` |
| **テスト** | `ComputeSeedTests` (5 ケース) |

#### GEN-14: `progress.should_update_completed(success: bool, is_interrupted: bool) -> bool`

| 項目 | 仕様 |
|---|---|
| **入力** | `success: bool`, `is_interrupted: bool` |
| **出力** | `bool` |
| **挙動** | `success=True かつ is_interrupted=False` のときのみ True |
| **副作用** | なし |
| **テスト** | `ShouldUpdateCompletedTests` (4 ケース、全パターン網羅) |

#### GEN-15: 各画像生成前の Interrupt チェック

| 項目 | 仕様 |
|---|---|
| **挙動** | `shared.state.interrupted` を毎ループ先頭で確認、True なら break |
| **位置** | `batch_runner._run_internal` の for ループ内 |
| **テスト** | ロジック上 L2 で確認 (生成中 Interrupt ボタン押下) |

#### GEN-16: `image_generator.create_fresh_p(original_p, new_prompt, new_negative=None) -> Processing`

| 項目 | 仕様 |
|---|---|
| **入力** | `original_p: StableDiffusionProcessingTxt2Img`, `new_prompt: str`, `new_negative: str | None` |
| **出力** | 新しい `Processing` オブジェクト |
| **挙動** | `copy.copy(original_p)` でシャローコピー + prompt/seed/batch_size=1/n_iter=1 上書き + transient state 初期化 |
| **重要** | `scripts` / `script_args` / `extra_generation_params` / `styles` / `hr_*` を**必ず維持** (ADetailer 等の動作に必須) |
| **テスト** | `CreateFreshPTests` (8 ケース) |

#### GEN-17: `image_generator.generate_one(p, replaced_prompt, seed, replaced_negative=None) -> (success, result, interrupted)`

| 項目 | 仕様 |
|---|---|
| **入力** | `p: Processing`, `replaced_prompt: str`, `seed: int`, `replaced_negative: str | None` |
| **出力** | `tuple[success: bool, result: Processed | None, interrupted: bool]` |
| **挙動** | `create_fresh_p` → `process_images` → エラー検知 → Interrupt 判定 |
| **副作用** | process_images は画像保存・履歴更新 (WebUI 側) |
| **テスト** | L1 では `Processing` のモックが困難なので L2 中心 |

#### GEN-18: 生成ループ開始前 `p.clear_prompt_cache()` 呼出

| 項目 | 仕様 |
|---|---|
| **位置** | `batch_runner._run_internal` のループ直前、1 回のみ |
| **目的** | クラス共有の cached_c / cached_uc を初期化 |
| **テスト** | L2 (R-03 で複数プロンプト生成時の崩れがないこと) |

#### GEN-19: `vram_manager.free_vram()` 呼出 → Phase 8-B で vram_recycler へ移管

| 項目 | 仕様 |
|---|---|
| **位置 (現)** | `batch_runner` で各画像生成後 |
| **位置 (8-B 後)** | `vram_recycler.py::postprocess_image` (AlwaysOn フック) |
| **トグル** | デフォルト OFF (Phase 8-B 仕様) |

#### GEN-20: ネガティブ自動展開 (collect_negative_additions + compose_negative_prompt)

統合 I/O:
- 入力: `body: str`, `variables: dict`, `negative_dict: dict`, `original_negative: str`
- 出力: `effective_negative: str`
- 挙動: body に出現する `$foo` に対応する negative 値を original の末尾に追加 (重複/空除外)
- テスト: `NegativeAdditionsTests` (7), `ComposeNegativePromptTests` (9)

#### GEN-21: 純粋関数 (GEN-20 の中身)

`expander.collect_negative_additions(body, variables, negative_dict) -> list[str]`
`expander.compose_negative_prompt(original, additions: list[str]) -> str`

詳細は上記テストファイル参照。

---

### B-bis. 変数呼出機構 (Variable Lookup Chain) — 維持すべき動線

> ⚠ **超重要**: 下記の **データ持ち方・呼出順・データ流**は仕様の正本。
> Phase 8 で意図せず変更すると Variable Manager や生成挙動が壊れる。
> **より良い方法があると判断した場合は必ずユーザーに確認して許可を取ること。**

#### VL-01: ストレージ

| 項目 | 仕様 |
|---|---|
| **ファイルパス** | `vars/variables.json` (リポジトリルート直下) |
| **スキーマバージョン** | v2 (`schema_version: 2`) |
| **構造** | ツリー (`categories: [{name, children, variables}]`) |
| **書き手** | (a) Variable Manager HTML (localStorage → POST /sync_variables), (b) ユーザーの手編集, (c) v1→v2 migration |
| **読み手** | Forge expander, Variable Manager 起動時 (GET /variables) |

#### VL-02: 変数エントリの形式

```json
{
  "name": "$char",                  ← $ プレフィックス込み (Manager 慣習)
  "positive": "1girl, alice",       ← メインプロンプトに展開される値
  "negative": "bad anatomy",        ← ネガティブに自動追加される値
  "updated_at": "2026-05-25T00:00:00Z",  ← Phase B last-write-wins
  "id": 123                          ← Manager 内部 ID (Forge は無視)
}
```

#### VL-03: 読込チェーン (Forge → 内部表現)

```
[STEP 1] variables_store.load_variables(path)
    ↓ ファイル open + json.load
[STEP 2] schema_version 判別 (v1 / v2)
    ↓ v2 → _load_v2_positive_flat (or v1 → _load_v1_flat)
[STEP 3] walk_variables(categories) でツリーを再帰 walk
    ↓
[STEP 4] 各 variable について:
    - _strip_dollar_prefix(name)    ← Hotfix-1: name の先頭 $ 除去
    - _normalize_value(positive)    ← Hotfix-2: 値前後の空白/; 除去
    ↓
[STEP 5] flat dict {name: [positive]} 構築 (キーは $ 抜き)
    ↓
[STEP 6] expander.expand_prompts に渡す
    ↓
[STEP 7] _find_var_ref_at で本文の $ 位置から最長一致でキーを検索
    ↓
[STEP 8] マッチしたら値で置換、しなければリテラル保持
```

#### VL-04: 書込チェーン (Manager → ファイル)

```
[STEP 1] Manager で変数編集 → state.save()
    ↓ debounce 500ms
[STEP 2] forge.js: syncToForgeNow()
    ↓ POST /vram_safe_batch/api/sync_variables
[STEP 3] v3b/prompt_expander: sync_variables ハンドラ
    ↓ mode="replace", categories=Manager のツリー全体
[STEP 4] variables_store.save_variables_v2(path, categories_tree)
    ↓ 既存ファイル → .bak.{ts} に退避
[STEP 5] _stamp_missing_updated_at で updated_at 補完
    ↓ json.dump で .tmp に書き → os.replace で原子置換
[STEP 6] _last_self_write_mtime を更新 (SSE self-loop 抑止)
```

#### VL-05: 双方向同期 (SSE)

```
[ファイル変更検出]
    ↓ file watcher (1 秒間隔 mtime polling)
[STEP 1] _watch_variables_file が mtime 変化を検出
    ↓ _last_self_write_mtime と比較 (自己書き込みなら skip)
[STEP 2] _change_subscribers の全 queue に "external_change" を put
    ↓
[STEP 3] SSE クライアント (Manager の EventSource) が受信
    ↓ fetchForgeVariables() で最新取得
[STEP 4] mergeLocalRemoteByUpdatedAt(local, remote) で variable 単位の last-write-wins マージ
    ↓ state.save() (suppressSync=true でループ防止)
[STEP 5] UI 再描画 + バッジ 🟢
```

#### VL-06: 名前文字種ルール (両側で同期)

| 位置 | 許容 | 禁止 |
|---|---|---|
| 先頭 1 文字 | 英字 / ひらがな / カタカナ / 漢字 / `_` | 数字 |
| 2 文字目以降 | 上記 + 数字 + `(` `)` `:` `、` | `=` / `;` / `,` / `$` / `/` / `{` `}` / `[` `]` / `.` / `|` / 空白 / 改行 |

Manager 側 `ui-ops.js::setupNameValidation` と Forge 側 `expander._DEF_RE` で**同一ルール**を維持。

#### VL-07: 「変更したいなら確認」ルール

以下の項目を Phase 8 で**意図せず変更してはならない**:

- `vars/variables.json` のスキーマ (`schema_version: 2`, `categories[].children[].variables[]` の入れ子)
- 変数エントリのフィールド名 (`name`, `positive`, `negative`, `updated_at`, `id`)
- `name` の `$` プレフィックス含む保存形式 (Manager 慣習、Forge 側で strip)
- 値末尾 `;` の strip ルール (Hotfix-2)
- updated_at の ISO8601 UTC 形式 (秒精度 + Z 末尾)
- API URL パス (`/vram_safe_batch/api/{set_jobs|status|peek_jobs|sync_variables|variables|variables/events}`)
- SSE ペイロード形式 (`{type: "external_change", mtime: float}`)
- file watcher の polling 間隔 (1.0 秒)

**より良い方法 (e.g., name から $ を削除して保存、schema v3 化) を提案する場合は、必ず:**
1. 影響範囲を分析 (Manager / Forge / Migration 全部)
2. 後方互換性の保証方法を提示
3. **ユーザーに確認して承認を取る**
4. その後にのみ実装

実装エージェントが独断で変更することを禁ずる。

### C. 履歴・再開機能

| ID | 機能 | 現状の場所 | Phase 移管先 |
|---|---|---|---|
| HIS-01 | history_v2 (schema v2) の load/save | history_v2.py | 共有モジュール維持 |
| HIS-02 | 起動時に旧 schema を `.bak.{ts}` にリネーム | history_v2.py | 8-D |
| HIS-03 | 生成中の進捗 update (completed/total/status) | v3b.py + history_v2.py | 8-D |
| HIS-04 | 再開モード判定 (チェック ON + 履歴選択) | v3b.py | 8-D |
| HIS-05 | 再開時に seed_mode / resolved_initial_seed を復元 | v3b.py | 8-D |
| HIS-06 | skip_until 個まで生成スキップ | v3b.py | 8-D |
| HIS-07 | resume 時に generation 設定 (width/height/cfg/steps/sampler) を復元 | v3b.py | 8-D |
| HIS-08 | resume 時に履歴の used_variables を inline_vars より優先 | v3b.py | 8-D |
| HIS-09 | 最大 5 件まで履歴保持 | history_v2.py | 共有モジュール維持 |

### D. API エンドポイント

| ID | 機能 | 現状の場所 | Phase 移管先 |
|---|---|---|---|
| API-01 | `POST /vram_safe_batch/api/set_jobs` (Variable Manager → サーバ受信) | v3b.py `_register_api` | 8-C |
| API-02 | `GET  /vram_safe_batch/api/status` (受信データ有無) | v3b.py | 8-C |
| API-03 | `GET  /vram_safe_batch/api/peek_jobs` (受信取得+クリア) | v3b.py | 8-C |
| API-04 | `POST /vram_safe_batch/api/sync_variables` (Manager → variables.json) | v3b.py | 8-C |
| API-05 | `GET  /vram_safe_batch/api/variables` (variables.json raw 返却) | v3b.py | 8-C |
| API-06 | `GET  /vram_safe_batch/api/variables/events` (SSE 変更通知) | v3b.py | 8-C |
| API-07 | file watcher (1 秒間隔 mtime polling) | v3b.py `_watch_variables_file` | 8-C |
| API-08 | self-write 抑止 (_last_self_write_mtime) | v3b.py | 8-C |
| API-09 | CORSMiddleware 登録 | v3b.py | 8-C |
| API-10 | `app.on_event("startup")` で watcher タスク起動 (Hotfix-3) | v3b.py | 8-C |

### E. Variable Manager 連携 (JS)

| ID | 機能 | 現状の場所 | Phase 移管先 |
|---|---|---|---|
| VM-01 | localStorage 自動同期 (state.save() で debounce 500ms POST) | sd_variable_manager_modules/state.js + forge.js | 触らない |
| VM-02 | 起動時 GET /variables で取り込み判定 | main.js | 触らない |
| VM-03 | SSE EventSource で外部編集を反映 | forge.js | 触らない (8-C で API は同 URL 維持) |
| VM-04 | updated_at last-write-wins マージ | forge.js | 触らない |
| VM-05 | 入力時の禁止文字自動除去 | ui-ops.js | 触らない |
| VM-06 | 同期ステータスバッジ (🟢🔵🟠🔴) | forge.js + sd_variable_manager.html | 触らない |
| VM-07 | 「🚀 Forge に送信」ボタン (builder text → set_jobs) | forge.js | 触らない |

### F. 起動時マイグレーション

| ID | 機能 | 現状の場所 | Phase 移管先 |
|---|---|---|---|
| MIG-01 | history_v2.migrate_legacy_if_needed | v3b.py 起動ブロック | 8-D |
| MIG-02 | variables_store.migrate_v1_to_v2_if_needed | v3b.py 起動ブロック | 8-C |

### G. 既存テスト (180/180 PASS 維持)

| ID | テストファイル | ケース数 |
|---|---|---|
| TST-01 | tests/test_expander.py | 約 95 |
| TST-02 | tests/test_variables_store.py | 約 45 |
| TST-03 | tests/test_compute_seed.py | 9 |
| TST-04 | tests/test_image_generator.py | 8 |
| TST-05 | tests/test_should_update_completed.py | 4 |
| TST-06 | tests/test_history_dropdown_focus.py | 7 |
| TST-07 | tests/test_pending_jobs.py | 5 |
| TST-08 | tests/test_history_v2.py | 7 |

---

## 回帰テスト戦略

### L1 (ユニットテスト) — 各 Phase 完了時の必須コマンド

```bash
python -m unittest discover tests 2>&1 | grep -E "^Ran|^OK|FAILED"
# 期待: Ran 180+ tests / OK
```

torch 必須の test_sdxl_cond_padding は事前から FAIL なので除外して数える。

### L2 (実機 WebUI) — Phase ごとの回帰チェックリスト

各 Phase 完了時に **下記 12 シナリオを順番に**実行し、全て同じ挙動になることを確認。

| # | シナリオ | 確認ポイント |
|---|---|---|
| R-01 | WebUI 起動 | ログにエラー無し、`API endpoints registered:` 表示 |
| R-02 | Script「v3b / Batch Resume」を選択 | UI が全表示、Accordion 8 種展開 |
| R-03 | メインプロンプト `$char, masterpiece`、`変数--- $char = alice;bob ---`、Generate | 2 枚生成、各画像 prompt に `alice` / `bob` |
| R-04 | 「🔄 メインから取得」→「🔢 枚数プレビュー」 | Dataframe 更新 + プレビュー表示 |
| R-05 | シードモード「固定」+ seed=12345 で 2 枚 | 両画像とも seed=12345 (infotext で確認) |
| R-06 | シードモード「連番」+ seed=-1 | 解決後 seed が記録され、+1 ずつ |
| R-07 | 生成中に Interrupt → 履歴ドロップダウンから選択 → 「再開する」チェック → Generate | 中断箇所から再開、画像番号歯抜けなし |
| R-08 | Variable Manager で `$char = alice;bob` 編集 | 500ms 内に variables.json 更新、バッジ 🟢 |
| R-09 | 外部エディタで variables.json 編集 + 保存 | 1〜2 秒で Manager に反映、トースト |
| R-10 | Variable Manager の変数に negative 設定 + メインで参照 | 生成画像 infotext の Negative に追加文字列 |
| R-11 | ADetailer ON + Hires.fix ON + v3b | 各画像で ADetailer 処理ログが出る |
| R-12 | sd-forge-couple ON + v3b | 領域別生成が動く |

### L3 (GPU 実機)
- VRAM Recycler ON で batch count 5 → 各画像後に `[VRAM Recycler]` ログ
- VRAM 不足で OOM が出ないこと

---

## Phase 8-A 実装手順 (内部リファクタ)

### 前提
- ブランチ: `feature/ui-cleanup-and-weighted-vars`
- 開始時に `git tag phase-8-a-start` を打つ

### タスク一覧 (subagent-driven で各タスク fresh subagent に渡す)

#### A1: 共通ヘルパー切り出し
**作業:**
- `scripts/vram_safe_batch_modules/ui_helpers.py` 新設
- v3b.py から移動: `_history_choices` / `_entry_detail` / `_parse_dropdown_index` / `_normalize_df` / `_compute_expansion_preview`
- v3b.py 側は `from .ui_helpers import ...` で再 export

**コミット:** `refactor(8-A1): ui_helpers.py を抽出`

**検証:** L1 全件 PASS + WebUI 起動して R-01 〜 R-04 確認

#### A2: API エンドポイント切り出し
**作業:**
- `scripts/vram_safe_batch_modules/api_endpoints.py` 新設
- v3b.py から移動: `_register_api` 全体、`_change_subscribers`, `_last_self_write_mtime`, `_VARS_WATCH_INTERVAL_SEC`
- v3b.py は `from .api_endpoints import register_api` + `script_callbacks.on_app_started(register_api)`

**コミット:** `refactor(8-A2): api_endpoints.py を抽出`

**検証:** L1 + L2 R-08 / R-09 / R-10 (Variable Manager 同期)

#### A3: 生成ループ切り出し
**作業:**
- `scripts/vram_safe_batch_modules/batch_runner.py` 新設
- v3b.py から移動: `_run_internal` の中身全部 (約 200 行)
- v3b.py の `_run_internal` は `from .batch_runner import run_batch` への薄ラッパー
- 関数シグネチャ: `run_batch(p, history_dropdown, resume_check, expansion_order_df, seed_mode, *, repo_root)` で副作用を最小化

**コミット:** `refactor(8-A3): batch_runner.py を抽出`

**検証:** L1 + L2 R-03, R-05, R-06, R-07 (生成ループ全般)

#### A4: UI 構築切り出し
**作業:**
- `scripts/vram_safe_batch_modules/ui_builder.py` 新設
- v3b.py から移動: `ui()` の中身全部 (約 600 行)
- 関数シグネチャ: `build_ui(is_img2img, base_dir) -> list[component]`
- イベントハンドラもすべて移動

**コミット:** `refactor(8-A4): ui_builder.py を抽出`

**検証:** L1 + L2 R-01, R-02, R-04, R-11, R-12 (UI と alwayson 拡張併用)

#### A5: 仕上げ (v3b.py を最小化)
**作業:**
- v3b.py を約 100 行に
- クラスシェル: `VRAMSafeBatchV3B(scripts.Script)` で `title/show/ui/run/_run_internal` のみ
- 起動時 migration 呼び出しはそのまま v3b.py トップに

**コミット:** `refactor(8-A5): v3b.py を thin wrapper 化 (1075→~100 行)`

**検証:** **R-01 〜 R-12 全件**

#### A6: Phase 8-A 完了タグ
```bash
git tag phase-8-a-done
```

### Phase 8-A 失敗時のロールバック
```bash
git reset --hard phase-8-a-start
```

---

## Phase 8-B 実装手順 (vram_recycler 分離)

### タスク一覧

#### B1: vram_recycler.py 新設
- `scripts/vram_recycler.py` 新規 (AlwaysOn 拡張)
- UI: `gr.Accordion("🧹 VRAM Recycler")` + `gr.Checkbox("画像ごとに VRAM を解放", value=False, info=...)`
- `postprocess_image(p, pp, enabled)` で `enabled` なら `vram_manager.free_vram()` + ログ
- L1: `tests/test_vram_recycler.py` 新規 (UI なしのロジック部分のみ)

**コミット:** `feat(8-B1): vram_recycler.py 新設 (AlwaysOn 拡張)`

#### B2: batch_runner から free_vram 呼出を撤去
- `batch_runner.py` 内の `vram_manager.free_vram()` 行を削除
- (vram_recycler が無効でも従来通りループ内で解放するか) → ユーザーは「UI トグル ON のみ動作」を指定。撤去で OK。
- ただし v3b の生成ループは複数枚連続生成で VRAM 蓄積するため、L3 で OOM が出ないかチェック

**コミット:** `refactor(8-B2): batch_runner から vram 解放呼出を撤去`

**検証:**
- vram_recycler チェック OFF で batch count 5 → 解放ログなし
- vram_recycler チェック ON で batch count 5 → 各画像後に `[VRAM Recycler]` ログ
- L1 全件 PASS
- L2 R-01 〜 R-12 全件
- L3 OOM 確認

#### B3: Phase 8-B 完了タグ
```bash
git tag phase-8-b-done
```

---

## Phase 8-C 実装手順 (prompt_expander 分離)

### タスク一覧

#### C1: prompt_expander.py 新設 (AlwaysOn の枠だけ)
- `scripts/prompt_expander.py` 新規
- UI: `gr.Accordion("$ Prompt Expander")` + 状態表示 + dynamic-prompts 衝突警告
- `process(p, *args)` で `p.prompt` を変数展開して `p.all_prompts` を書き換え
- expander の既存ロジックを呼ぶだけ

**コミット:** `feat(8-C1): prompt_expander.py 新設 (AlwaysOn 拡張)`

#### C2: API 移管
- `api_endpoints.py` の `_register_api` を 2 つに分割:
  - prompt_expander が登録するもの: `/sync_variables` `/variables` `/variables/events` `/peek_jobs` `/set_jobs` `/status`
  - batch_resume が登録するもの: なし (履歴 API は v3b にも無かった)
- file watcher も prompt_expander 側に
- script_callbacks.on_app_started を prompt_expander 側で登録

**コミット:** `refactor(8-C2): variables 系 API を prompt_expander に移管`

#### C3: batch_runner から事前展開を撤去
- batch_runner.py の `expander.expand_prompts` 呼出を撤去
- 代わりに p.all_prompts を読み込んで各画像にイテレート (prompt_expander が事前展開済み)
- 展開順 UI の値は batch_runner が「展開順」として prompt_expander に伝える必要がある
  - Forge の機構: `p.script_args` に展開順を入れる or グローバル変数
  - シンプル案: 展開順 UI を prompt_expander 側に移し、batch_resume は履歴/再開だけ担当

**判断要:** 展開順 UI を 8-C 中で prompt_expander に移すか、8-D で整理するか

**コミット:** `refactor(8-C3): batch_runner の事前展開を撤去`

#### C4: ネガティブ自動展開も prompt_expander へ
- prompt_expander の process フックで p.negative_prompt を `compose_negative_prompt` で書き換え
- batch_runner 側のネガティブ計算を撤去

**コミット:** `refactor(8-C4): ネガティブ自動展開を prompt_expander に移管`

#### C5: dynamic-prompts 衝突警告
- prompt_expander の起動時に `os.path.isdir(extensions/sd-dynamic-prompts)` を検出
- 両方 ON ならログに警告 + UI に注意書き

**コミット:** `feat(8-C5): dynamic-prompts 共存警告`

**検証:**
- L1 全件 PASS
- L2 R-01 〜 R-12 全件
- L2 追加: Script 未選択でも `$char` 展開が動く

#### C6: Phase 8-C 完了タグ
```bash
git tag phase-8-c-done
```

---

## Phase 8-D 実装手順 (batch_resume 整理)

### タスク一覧

#### D1: ファイルリネーム
- `scripts/vram_safe_batch_v3b.py` の内容を `scripts/batch_resume.py` にコピー
- `title()` を「VRAM Safe Batch v3b」→「Batch Resume」に変更
- v3b.py は **deprecation スタブ** (import + print 警告のみ)

**コミット:** `refactor(8-D1): vram_safe_batch_v3b.py を batch_resume.py にリネーム`

#### D2: 不要コード削除
- 既に prompt_expander / vram_recycler に移管済みのコードを batch_resume から削除
- 起動時 migration の `migrate_v1_to_v2_if_needed` は prompt_expander 側へ
- 起動時 `migrate_legacy_if_needed` は batch_resume 側に残す

**コミット:** `refactor(8-D2): batch_resume から移管済みコードを削除`

#### D3: deprecation スタブ
- v3b.py:
  ```python
  print("[VRAM Safe Batch] v3b は batch_resume にリネームされました。")
  ```

**コミット:** `chore(8-D3): v3b.py を deprecation スタブ化`

**検証:**
- L1 全件 PASS
- L2 R-01 (Script 一覧に「Batch Resume」)、R-02 〜 R-12 全件

#### D4: Phase 8-D 完了タグ
```bash
git tag phase-8-d-done
```

---

## Phase 8-E 実装手順 (text_replace 新設、Pending-2 統合)

### タスク一覧

#### E1: text_replace.py 新設 (UI 骨組み)
- `scripts/text_replace.py` 新規 (AlwaysOn UI のみ)
- UI: `gr.Accordion("🔎 Text Replace", open=False)` + 検索/置換入力フィールド
- 純粋関数は既存 `text_tools.py` を流用

**コミット:** `feat(8-E1): text_replace.py 新設`

#### E2: フローティングパネル CSS
- `text_replace.py` 内に CSS を `Blocks.load(_js=...)` で注入
- `position: absolute` でメインプロンプト欄右上配置

**コミット:** `feat(8-E2): フローティングパネル CSS`

#### E3: Ctrl+F バインド JS
- `Blocks.load(_js=...)` で keydown listener
- textarea フォーカス時のみ `Ctrl+F` 横取り、`Esc` で閉じる

**コミット:** `feat(8-E3): Ctrl+F トグル JS`

#### E4: 検索・置換ロジック JS
- `text_tools.py` のロジックを呼ぶ click handler
- マッチ件数 `N / M` 表示、`▲▼` ジャンプで `setSelectionRange`
- L1: `tests/test_text_tools.py` を再有効化 (既存テスト復活)

**コミット:** `feat(8-E4): 検索・置換 JS`

**検証:**
- L1 全件 PASS
- L2 R-01 〜 R-12 全件
- L2 追加: メインプロンプトで Ctrl+F → パネル → 検索/置換/Undo

#### E5: Phase 8-E 完了タグ
```bash
git tag phase-8-e-done
```

---

## Superpowers プラグイン活用ポイント

プロジェクトに `superpowers@5.1.0` がインストール済み。各場面で活用:

| Superpowers Skill | 本プロジェクトでの活用 |
|---|---|
| `superpowers:writing-plans` | 各 Phase の詳細プラン作成 (本ファイルがその成果物) |
| `superpowers:subagent-driven-development` | **Phase 8-A の各タスク (A1〜A5) を fresh subagent に渡して実装**。コンテキスト分離により高品質 |
| `superpowers:test-driven-development` | 各拡張の純粋関数を TDD で実装 (RED → GREEN → REFACTOR の徹底) |
| `superpowers:verification-before-completion` | **「完了」と言う前に L2 シナリオを実機で実行**して証拠を出す |
| `superpowers:systematic-debugging` | Pending-1 (ADetailer + Hires.fix「同じ画像 2 枚」) の根本原因調査 |
| `superpowers:using-git-worktrees` | Phase 8-B と 8-E は依存関係が薄いので worktree で並行実装可 |
| `superpowers:requesting-code-review` | 各 Phase 完了時に subagent でコードレビューを依頼 |
| `superpowers:finishing-a-development-branch` | 全 Phase 完了後、PR 作成時に branch finalize |

### 推奨呼出タイミング

```
[Phase 開始時]
  → superpowers:writing-plans (このファイル参照)
  → superpowers:test-driven-development (テスト先行)

[各タスク実装]
  → superpowers:subagent-driven-development
    → 子: superpowers:test-driven-development
    → 子: superpowers:verification-before-completion

[Phase 完了時]
  → superpowers:requesting-code-review (subagent でレビュー)
  → L2 動作確認
  → git tag phase-X-done
  → ユーザー承認待ち

[全 Phase 完了時]
  → superpowers:finishing-a-development-branch
```

---

## ロールバック早見表

| 状況 | コマンド |
|---|---|
| 現在の Phase で動作怪しい → 開始前に戻す | `git reset --hard phase-X-start` |
| ある Phase 完了直後でやり直したい | `git reset --hard phase-X-done` |
| 特定コミットだけ取り消したい | `git revert <commit-hash>` |
| Phase 8 全部やめたい | `git reset --hard phase-8-a-start` (Phase 8 開始前) |

タグ一覧確認: `git tag --list 'phase-*'`

---

## 開始前チェックリスト

- [ ] `git status` で未コミット変更が無いこと
- [ ] `git tag phase-8-start` を打つ
- [ ] 本ファイル (`docs/phase8/implementation_playbook.md`) を毎 Phase の参照源にする
- [ ] `docs/phase8/refactoring_plan.html` をユーザーが承認済みであること
- [ ] L1 (180 件) PASS 状態であること

## 各 Phase 完了時チェックリスト

- [ ] L1 (180 件) PASS
- [ ] L2 (R-01 〜 R-12) 全件 OK
- [ ] git tag `phase-X-done` を打つ
- [ ] ユーザーに動作確認を依頼し承認を得る
- [ ] **承認後**に次 Phase へ
