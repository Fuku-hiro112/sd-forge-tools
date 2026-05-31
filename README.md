# sd-forge-tools

## 概要

[stable-diffusion-webui-forge](https://github.com/lllyasviel/stable-diffusion-webui-forge) に被せて使う画像生成ワークフロー支援ツール群。`$変数` を使ったプロンプトのバッチ生成・履歴/中断再開、通常生成での変数展開、画像ごとの VRAM 解放、変数編集スタンドアロン UI、プロンプト textarea 上の Ctrl+F 検索置換、を提供する。元々は `vram_safe_batch_v3b.py` (1075 行モノリス) に詰め込んでいた機能を、Phase 8 リファクタで責務単位の独立拡張に分割した。Claude Code を使った AI 駆動開発で実装し、`tdd-forge` + `superpowers` Skill で TDD と多段検証 (L1/L2/L3) を必ず通すワークフロー。forge 本体は upstream のままで、本リポジトリのファイルだけを上書き配置すれば動く。

## 成果物 (3 拡張 + 1 関連 UI + 1 JS ウィジェット)

| 成果物 | 種別 | 主な役割 |
|---|---|---|
| **[Batch Resume](#1-batch-resume)** | Script | `$変数` 直書きプロンプトのバッチ展開 + 履歴 + 中断再開 |
| **[Prompt Expander](#2-prompt-expander)** | AlwaysOn | 通常生成でも `$変数` を展開 + variables 同期 API + SSE |
| **[VRAM Recycler](#3-vram-recycler)** | AlwaysOn | 画像ごとに VRAM を解放 (CUDA `empty_cache` + `gc.collect`) |
| **[SD Variable Manager](#4-sd-variable-manager)** | スタンドアロン HTML | ブラウザ単体で開く変数編集 UI。Prompt Expander の REST/SSE と双方向同期 |
| **[Text Replace (Ctrl+F)](#5-text-replace-ctrlf)** | JS ウィジェット | プロンプト textarea 上で VSCode 風 Ctrl+F 検索/置換パネルを開く |

---

### 1. Batch Resume

📁 [`scripts/batch_resume.py`](scripts/batch_resume.py)

#### 機能

メインプロンプトに `$char, 1girl, $outfit, best quality` のように **変数を直接埋め込む** だけで、定義値の総当りで複数枚生成する Script 拡張。

- 変数定義は 3 通り: `vars/variables.json` (永続) / プロンプト内ブロック `変数--- $char = alice;bob ---` / 行頭インライン `$char = alice;bob`
- 「📊 展開順」で外側→内側ループ順を指定 (上が外側=変化が遅い)
- 「🔄 メインプロンプトから取得」ボタンで展開順を自動入力
- **履歴 v2** で各バッチを保存、エラーや PC 再起動で中断しても「選択した履歴から再開」で進捗復元

#### 作成意図

- forge 標準の X/Y/Z plot や prompts_from_file は「リストファイルを別途用意」「事前にすべての行を展開」の前提で、**プロンプト本文に変数を埋め込む書き味** が得られなかった
- 数百枚規模の生成で **途中 OOM / WebUI クラッシュ / PC 再起動** が起きると最初からやり直しになる現状を解決したい
- v3b モノリスでは「履歴・再開」と「変数展開」が癒着していた → **再開ロジックだけを Script として独立** させ、AlwaysOn の Prompt Expander と切り離した

#### 設計ドキュメント

- 全体設計: [`docs/phase8/refactoring_plan.html`](docs/phase8/refactoring_plan.html)
- UI 分割の合意: [`docs/phase8/c_ui_restructure.html`](docs/phase8/c_ui_restructure.html)

---

### 2. Prompt Expander

📁 [`scripts/prompt_expander.py`](scripts/prompt_expander.py)

#### 機能

Batch Resume を選択していない **通常生成 / X/Y/Z plot / forge 標準バッチ** でも、メインプロンプトの `$変数` を展開して複数枚生成する **AlwaysOn 拡張**。

- 起動時 `vars/variables.json` を v1 → v2 形式へ自動マイグレーション
- 展開順 UI / シードモード / 記法ガイド / 「メインプロンプトから取得」ボタンを内蔵
- **FastAPI エンドポイント + SSE** を `/vram_safe_batch/api/sync_variables`, `/vram_safe_batch/api/variables`, `/vram_safe_batch/api/variables/events` として登録 → 外部ツール (エディタ拡張など) から variables.json を同期可能
- `sd-dynamic-prompts` 拡張との `$varname` 構文衝突を起動時に検出して警告

#### 作成意図

- Batch Resume は「Script 選択 = 他の Script (Hires.fix の挙動とか) と排他」が制約だった
- 普段の生成フローでも `$char` だけサクッと展開したいケースが多く、**Script 排他制約を回避** したかった
- AlwaysOn 化することで、forge 標準ループ・X/Y/Z plot・第三者拡張のバッチループとも共存可能に
- v3b では variables 系 API が `api_endpoints.py` に同居していた → **register_variables_api として prompt_expander 側に移管** し、API 提供と展開ロジックを 1 拡張に閉じた

#### 設計ドキュメント

- 3 案比較 (保守/標準/攻め) からの選択: [`docs/phase8/c_design_choices.html`](docs/phase8/c_design_choices.html)
- 双方向同期の経緯: [`docs/archive/variable_manager_sync_design.html`](docs/archive/variable_manager_sync_design.html)
- `_register_api` → `app.on_event("startup")` 切替: [`docs/archive/hotfix3_event_loop_design.html`](docs/archive/hotfix3_event_loop_design.html)

---

### 3. VRAM Recycler

📁 [`scripts/vram_recycler.py`](scripts/vram_recycler.py)

#### 機能

UI トグル ON で、各画像生成後に `torch.cuda.empty_cache()` + `gc.collect()` を呼び VRAM を解放する **AlwaysOn 拡張**。

- デフォルト OFF (副作用なし、軽量)
- `sorting_priority = 19` で neveroom 拡張 (18) の直後に動作
- forge 標準バッチ / X/Y/Z plot / Hires.fix 等、**生成ループ種別を問わず** 効く

#### 作成意図

- 元々は v3b の独自生成ループ内に焼き込まれていた処理 → forge 標準ループでは効かなかった
- 連続生成で VRAM が単調増加する環境 (特に SDXL + Hires.fix + ADetailer 併用時) を救いたかった
- **生成ループに依存しない AlwaysOn 化** により、ユーザーが「VRAM 解放したい時はトグル ON するだけ」で済むように責務を最小化

#### 設計ドキュメント

- 責務分離の全体図: [`docs/phase8/refactoring_plan.html`](docs/phase8/refactoring_plan.html) (「画像ごと VRAM 解放」セクション)

---

### 4. SD Variable Manager

📁 [`scripts/sd_variable_manager.html`](scripts/sd_variable_manager.html) + [`scripts/sd_variable_manager_modules/`](scripts/sd_variable_manager_modules/) + [`scripts/sd_variable_presets.json`](scripts/sd_variable_presets.json)

#### 機能

forge とは別プロセスとして **ブラウザで HTML を直接開く** 変数編集スタンドアロン UI。Prompt Expander が `/vram_safe_batch/api/variables` で公開している REST + SSE と双方向同期する。

- カテゴリ階層 (再帰) + 変数 (positive/negative) を GUI で編集
- ドラッグ&ドロップで並び替え・階層移動
- テーマ切替 (`Graphite` / 他複数) + プリセット Merge Import ([`sd_variable_presets.json`](scripts/sd_variable_presets.json) から定番タグ集を流し込み可能)
- 起動時に Forge と疎通確認し、Manager 側が空なら Forge 側の `variables.json` を黙って取り込み
- 編集すると SSE で Forge 側 (= prompt_expander) へ即時同期 → forge 再起動なしで `$変数` が即反映

#### 作成意図

- `vars/variables.json` を手で編集していたが、200 件超になると **JSON 直編集は破綻** した (id 衝突、構造ミス)
- forge のメイン UI に組み込む形では「変数編集中は生成画面が遮られる」「ツリー編集のような複雑 UI には forge の Gradio が向かない」課題があった
- **forge とは独立した HTML** にすることで、別ディスプレイ/別タブで編集しながら本体は生成を回せる構成にした
- バックエンド (`prompt_expander.py` の REST + SSE) を分離したことで、将来 VSCode 拡張など別フロントからも差し替え可能

#### 使い方

```bash
# ブラウザでファイルを直接開く (file:// 経由でも CORS は prompt_expander 側で allow_origins=* 済み)
start scripts/sd_variable_manager.html      # Windows
xdg-open scripts/sd_variable_manager.html   # Linux
open scripts/sd_variable_manager.html       # macOS
```

forge が起動していれば右上の Sync バッジが緑になり、編集が即同期される。

#### 設計ドキュメント

- 双方向同期 (Phase B) の経緯: [`docs/archive/variable_manager_sync_design.html`](docs/archive/variable_manager_sync_design.html)
- 関連: [`vars/variables.example.json`](vars/variables.example.json) — variables.json の v2 スキーマサンプル (実体は個人データを含むため git 管理外)

---

### 5. Text Replace (Ctrl+F)

📁 [`javascript/text_replace.js`](javascript/text_replace.js)

#### 機能

プロンプト textarea にフォーカス中の **Ctrl+F** で、VSCode 風のフローティング検索置換パネルを開く純 JS ウィジェット。

- 検索・前後移動 (Enter / Shift+Enter)
- 1 件置換 / 全置換
- マッチは `setSelectionRange` でネイティブ選択ハイライト
- 検索対象 textarea セレクタ: `*:is([id*='_toprow'] [id*='_prompt'], .prompt) textarea` (forge の `edit-attention.js` と同じ流儀)
- 検索/置換ロジックは [`scripts/vram_safe_batch_modules/text_tools.py`](scripts/vram_safe_batch_modules/text_tools.py) の意味論を JS で **ミラー実装** (Python 側で挙動を `tests/` カバーし、JS 側はそれを移植)

#### 作成意図

- `$変数` を多用するワークフローでは、メインプロンプトが数百〜数千字になり **ブラウザ標準の検索が効かない** (textarea 内テキストは Ctrl+F で検索できない)
- 「特定タグの一括置換」をしたいときに gen タブ全体をマウス選択 → 別エディタに貼り → 戻す、という手間が常にあった
- forge は `javascript/*.js` を起動時に自動 `<script>` 読込してくれる仕様を利用し、**Python 拡張を増やさず純 JS だけで完結** させた (Python 側に依存を持たないため壊れにくい)
- Python 側 `text_tools.py` を意味論の "正本" として置き、JS 実装は単なる移植にした → ロジック検証は L1 unit テストで担保、JS 側は薄く保つ

#### 使い方

1. forge を起動して通常通り gen タブ (`txt2img` / `img2img`) を開く
2. メインプロンプト textarea をクリックしてフォーカス
3. **Ctrl+F** で検索パネルが右上に出現
4. 検索語 → Enter で次のマッチへ、置換語入力 → 全置換ボタン
5. Esc でパネルを閉じる

#### 設計ドキュメント

- 設計計画書: [`docs/phase8/f_text_replace_plan.html`](docs/phase8/f_text_replace_plan.html)

---

## 共有モジュール: `scripts/vram_safe_batch_modules/`

3 拡張が共通で使う内部実装ロジック群 (歴史的経緯で v3b モノリスの名前を引き継いでいる)。

| モジュール | 用途 | 使用元 |
|---|---|---|
| `history_v2.py` | バッチ履歴の保存/読込/再開 | Batch Resume |
| `api_endpoints.py` | FastAPI ルート登録ヘルパ | Batch Resume / Prompt Expander |
| `expander.py` | `$変数` パース・総当り展開 | Prompt Expander |
| `variables_store.py` | variables.json 読み書き + v1→v2 マイグレーション | Prompt Expander |
| `pending_jobs.py` | 展開後のジョブキュー管理 | Prompt Expander |
| `vram_manager.py` | `free_vram()` 実装 | VRAM Recycler |
| `ui_helpers.py` / `text_tools.py` / `progress.py` / `batch_runner.py` / `job_builder_*.py` / `image_generator.py` / `ui_builder.py` | 内部ユーティリティ | 各拡張から間接利用 |

---

## このプロジェクトでの AI 駆動開発の進め方

「動けば OK」では事故 (CUDA silent fallback、`scripts/` auto-import 起動不能化、VRAM leak、UI 見える ≠ 動く) が頻発する分野のため、**プロジェクト固有 Skill + 汎用 Skill + 設計提案の HTML 化** を組み合わせて品質を担保している。

### 使用している Skill

| Skill | 出所 | 役割 |
|---|---|---|
| [`tdd-forge`](.claude/skills/tdd-forge/SKILL.md) | **本プロジェクト固有** (自作) | forge 特有の落とし穴に対応した TDD + L1/L2/L3 多段検証ワークフロー |
| [`superpowers`](https://github.com/obra/superpowers) | 公式 Claude Code プラグイン | `brainstorming` (発散) → `writing-plans` (実装計画) → `executing-plans` (TDD 駆動実装) → `verification-before-completion` (完了前検証) → `subagent-driven-development` (Verifier 分離) のフレーム |

`superpowers` で全体の進め方 (発散 → 計画 → 実装 → 検証) を固定し、その中の「実装+検証」フェーズで forge 固有の `tdd-forge` が発動する、という二段構え。

### `tdd-forge` の 5 フェーズ (抜粋)

| 段階 | やること |
|---|---|
| **Phase 0: Pre-flight** | 修正対象とその呼び出し元 / 被呼び出し関数を実体確認。バグ報告は実際に再現してから RED へ |
| **Phase 1: RED** | 「正しい理由で失敗」させる。ImportError / fixture 失敗での "失敗" は無効。失敗ログを保存 |
| **Phase 2: GREEN** | 最小修正。例外握り潰し / hardcode / monkey patch / 「とりあえず None」は禁止 |
| **Phase 3: REFACTOR** | テスト緑を維持して直接周辺のみ整理。スコープクリープ禁止 |
| **Phase 4: VERIFY** | L1 (unit) / L2 (UI 操作 + screenshot + DOM 両輪) / L3 (CUDA 実使用 + dtype 一致 + 連続 VRAM 推移) で検証 |

### Verifier sub-agent への blind 検証委譲

3 ファイル以上・100 行以上の改修、ユーザー報告 L2 不具合、全 L3 案件は **実装者が VERIFY を別 sub-agent に委譲** する。実装方針を渡さず症状と期待観測だけを伝え、自己検証バイアスを排除する。

### 設計議論を HTML で残す ── 「AI に提案させて私が代案を出す」

リファクタや大規模機能追加では、Claude に **複数案を HTML ドキュメントとして出力させる** ルールを敷いている。テキストだけだと「読み流して同意してしまう」事故が起きやすいため、図解・比較表・ホバー解説付き HTML にすることで:

- 自分が **冷静に評価できる** (テキストの羅列より圧倒的に把握しやすい)
- **代案を出しやすい** (どこに反対するかが明確になる)
- 後から **判断の経緯を辿れる** (なぜ A 案を選んだかが残る)

実物は [`docs/`](docs/) に蓄積。Phase 8 (1075 行の `vram_safe_batch_v3b.py` を 3 拡張に分割) の作業はすべてこのプロセスを踏んでいる。

| ドキュメント | 種別 |
|---|---|
| [`docs/phase8/refactoring_plan.html`](docs/phase8/refactoring_plan.html) | 全体設計 (ユーザー承認用) |
| [`docs/phase8/c_design_choices.html`](docs/phase8/c_design_choices.html) | **3 案比較 (保守/標準/攻め)** ユーザーが選択 |
| [`docs/phase8/c_ui_restructure.html`](docs/phase8/c_ui_restructure.html) | UI 移管の事前合意 |
| [`docs/phase8/f_text_replace_plan.html`](docs/phase8/f_text_replace_plan.html) | 派生機能の設計 |
| [`docs/phase8/implementation_playbook.md`](docs/phase8/implementation_playbook.md) | Claude 実装エージェント向け詳細手順 |
| [`docs/archive/`](docs/archive/) | 採用されなかった案・上書きされた設計 (経緯保存) |

これらは「実装後にまとめた docs」ではなく **「Claude が提案 → 私が承認/代案 → 実装着手」の順** で書かれている (= AI に主導権を渡さない設計プロセス)。

### Git 運用

`CLAUDE.md` で Git Flow (main/develop/feature/*) を採用。Claude は feature/* で作業し、main/develop への直接コミット禁止。

---

## ディレクトリ構成

```
.
├── .claude/skills/tdd-forge/SKILL.md      Claude に守らせる TDD/検証ルール (自作)
├── docs/                                   設計議論 (HTML) / 過去案 / 作業メモ
│   ├── README.md                           docs 目次
│   ├── phase8/                             責務分離の設計・選択ドキュメント
│   ├── archive/                            過去の設計案 (現在の正本ではない)
│   ├── guides/                             ユーザー向け使い方ガイド
│   ├── images/                             ガイドから参照されるスクショ
│   └── user_memo/                          ユーザー手書きの修正案メモ
├── scripts/                                forge の scripts/ にそのまま置く
│   ├── batch_resume.py                     Script 拡張: バッチ展開 + 履歴 + 再開
│   ├── prompt_expander.py                  AlwaysOn 拡張: 通常生成でも $変数 展開 + API
│   ├── vram_recycler.py                    AlwaysOn 拡張: 画像ごと VRAM 解放
│   ├── sd_variable_manager.html            スタンドアロン変数編集 UI 本体
│   ├── sd_variable_manager_modules/        変数 UI の JS モジュール群
│   ├── sd_variable_presets.json            Merge Import 用の定番タグプリセット
│   └── vram_safe_batch_modules/            複数拡張で共有する内部実装
├── javascript/                             forge が起動時に自動 <script> 読込
│   └── text_replace.js                     Ctrl+F 検索置換ウィジェット
└── vars/
    └── variables.example.json              variables.json v2 スキーマのサンプル
                                            (実体 vars/variables.json は git 管理外)
```

---

## セットアップ

### 前提

- [stable-diffusion-webui-forge](https://github.com/lllyasviel/stable-diffusion-webui-forge) がインストール済み
- CUDA 対応 GPU + PyTorch
- Python 3.10+ (forge 同梱の venv 推奨)

### インストール

```bash
FORGE=/path/to/stable-diffusion-webui-forge

# 1. scripts/ をコピー (Script + AlwaysOn 拡張 + SD Variable Manager UI + 共有 modules)
cp -r scripts/* $FORGE/scripts/

# 2. javascript/ をコピー (Ctrl+F 検索置換)
cp -r javascript/* $FORGE/javascript/

# 3. vars/variables.json を作成 (空ファイルでも OK。サンプルを参考に)
mkdir -p $FORGE/vars
cp vars/variables.example.json $FORGE/vars/variables.json   # サンプルから始める場合

# 4. (任意) tdd-forge skill を forge プロジェクトにも反映する場合
cp -r .claude/skills/tdd-forge $FORGE/.claude/skills/
```

forge を再起動すると:

- Script ドロップダウン → 「Batch Resume」
- Always-On アコーディオン → 「Prompt Expander」「🧹 VRAM Recycler」
- プロンプト textarea にフォーカスして **Ctrl+F** → 検索置換パネル
- ブラウザで `scripts/sd_variable_manager.html` を開く → 変数編集 UI

の 5 つが利用可能になる。

## 注意点

- `scripts/` 直下に **テスト/実行スクリプト** (`test_*.py`, `tmp_*.py`, `debug_*.py`) を置くと auto-import で WebUI が起動しなくなる。テストは forge の `tests/` 配下に置くこと
- `.pyc` キャッシュが残っていると古いコードが動く。移動/削除時は対応する `__pycache__/*.pyc` も消す
- CUDA fallback (CPU 動作になっていないか) は VERIFY 時に `device.type == 'cuda'` で確認すること (`tdd-forge` Skill 参照)
- `vram_safe_batch_modules/` という共有モジュール名は v3b モノリスの名残。3 拡張すべてが import パスとして使っているため改名していない

## ライセンス

MIT
