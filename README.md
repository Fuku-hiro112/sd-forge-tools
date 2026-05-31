# sd-forge-tools

## 概要

[stable-diffusion-webui-forge](https://github.com/lllyasviel/stable-diffusion-webui-forge) の `scripts/` 配下に配置して使う、自作の画像生成ユーティリティ群。リスト組み合わせの一括生成 (`vram_safe_batch`)、変数置換による Always-On プロンプト展開 (`prompt_expander` + `sd_variable_manager`)、VRAM の段階的開放 (`vram_recycler`) を提供する。AI 駆動開発で実装し、`tdd-forge` Skill で TDD と多段検証 (L1/L2/L3) を必ず通すワークフローを整備している。forge 本体は upstream のままで、本リポジトリのファイルだけを上書き配置すれば動く。

## 使用技術

- Python 3.10+ (forge の venv で動作)
- PyTorch (CUDA)
- Gradio (forge の UI フレームワーク)
- JavaScript / HTML (sd_variable_manager の独自 UI)

## 機能

- **`vram_safe_batch`** — `{1} {2} {3}` のようなプレースホルダで複数リストの組み合わせを一括生成。途中中断/再開、進捗保存、API エンドポイント拡張に対応 (v3a / v3b は段階リファクタの履歴版)
- **`prompt_expander`** — `$char` のようなメインプロンプト変数を Always-On パターンで展開。Batch Resume Script 未選択時も効く
- **`sd_variable_manager`** — 変数定義の専用 UI (Gradio + 独自 JS/HTML)。テーマ切替・DnD・履歴管理・テンプレ
- **`vram_recycler`** — 生成サイクル間で VRAM を段階的に開放するヘルパー

## このプロジェクトでの AI 駆動開発の進め方

「動けば OK」では事故 (CUDA silent fallback、`scripts/` auto-import 起動不能化、VRAM leak、UI 見える ≠ 動く) が頻発する分野のため、**プロジェクト固有 Skill + 汎用 Skill (Superpowers) + 設計提案を HTML で明文化** という 3 つの仕組みを組み合わせて品質を担保している。

### 使用している Skill

| Skill | 出所 | 役割 |
|---|---|---|
| [`tdd-forge`](.claude/skills/tdd-forge/SKILL.md) | **本プロジェクト固有** (自作) | forge 特有の落とし穴 (auto-import 事故 / CUDA fallback / VRAM leak / UI 検証) に対応した TDD + L1/L2/L3 多段検証ワークフロー |
| [`superpowers`](https://github.com/obra/superpowers) | 公式 Claude Code プラグイン | `brainstorming` (発散) → `writing-plans` (実装計画) → `executing-plans` (TDD 駆動実装) → `verification-before-completion` (完了前検証) → `subagent-driven-development` (Verifier 分離) のフレーム。`tdd-forge` の上位の進行ルールとして使う |

`superpowers` で全体の進め方 (発散 → 計画 → 実装 → 検証) を Skill 駆動で固定し、その中の「実装+検証」フェーズで forge 固有の `tdd-forge` が発動する、という二段構え。

### `tdd-forge` の 5 フェーズ (抜粋)

| 段階 | やること |
|---|---|
| **Phase 0: Pre-flight** | 修正対象とその呼び出し元 / 被呼び出し関数を実体確認。バグ報告は実際に再現してから RED へ |
| **Phase 1: RED** | 「正しい理由で失敗」させる。ImportError / fixture 失敗での "失敗" は無効。失敗ログを保存 |
| **Phase 2: GREEN** | 最小修正。例外握り潰し / hardcode / monkey patch / 「とりあえず None」は禁止 |
| **Phase 3: REFACTOR** | テスト緑を維持して直接周辺のみ整理。スコープクリープ禁止 |
| **Phase 4: VERIFY** | L1 (unit) / L2 (UI 操作 + screenshot + DOM 両輪) / L3 (CUDA 実使用 + dtype 一致 + 連続 VRAM 推移) で検証 |

### Verifier sub-agent への blind 検証委譲

3 ファイル以上・100 行以上の改修、ユーザー報告 L2 不具合、全 L3 案件は **実装者が VERIFY を別 sub-agent に委譲** する。実装方針を渡さず症状と期待観測だけを伝え、自己検証バイアスを排除する (superpowers の `subagent-driven-development` を `tdd-forge` 流に運用)。

### 設計議論を HTML で残す ── 「AI に提案させて私が代案を出す」

リファクタや大規模機能追加では、Claude に **複数案を HTML ドキュメントとして出力させる** ルールを敷いている。テキストでの説明だけだと「読み流して同意してしまう」事故が起きやすいため、図解・比較表・ホバー解説付き HTML にすることで:

- 自分が **冷静に評価できる** (テキストの羅列より圧倒的に把握しやすい)
- **代案を出しやすい** (どこに反対するかが明確になる)
- 後から **判断の経緯を辿れる** (なぜ A 案を選んだかが残る)

実物は [`docs/`](docs/) に蓄積。Phase 8 (1075 行のモノリス `vram_safe_batch_v3b.py` を 4 拡張に分割) の作業はすべてこのプロセスを踏んでいる:

| ドキュメント | 種別 | 目的 |
|---|---|---|
| [`docs/phase8/refactoring_plan.html`](docs/phase8/refactoring_plan.html) | 全体設計 | Phase 8 全体の責務分離設計図 (ユーザー承認用) |
| [`docs/phase8/c_design_choices.html`](docs/phase8/c_design_choices.html) | **3 案比較 (保守/標準/攻め)** | Claude が出した複数案。ユーザーがトレードオフを評価して選択 |
| [`docs/phase8/c_ui_restructure.html`](docs/phase8/c_ui_restructure.html) | UI 移管設計 | 大規模 UI 移管の事前合意 |
| [`docs/phase8/f_text_replace_plan.html`](docs/phase8/f_text_replace_plan.html) | 新機能設計 | Ctrl+F 検索置換パネルの設計 |
| [`docs/phase8/implementation_playbook.md`](docs/phase8/implementation_playbook.md) | 実装プレイブック | Claude 実装エージェント向けの詳細手順 (機能 ID / 不変条件 / Phase 別手順) |
| [`docs/archive/`](docs/archive/) | 過去設計 | 採用されなかった案・上書きされた設計 (経緯保存) |

ブラウザで HTML を開くと、SVG / 比較表 / 専門用語ホバー解説付きで読める。これらは「実装後にまとめた docs」ではなく **「Claude が提案 → 私が承認/代案 → 実装着手」の順** で書かれている (= AI に主導権を渡さない設計プロセス)。

### 指示スタイル

- 設計判断は A 案 / B 案 / C 案 を HTML で出させ、ユーザーが選択 (上記参照)
- 大規模リファクタ前は memory (`.claude/projects/*/memory/`) で「過去にやらかしたパターン」を確認
  - 例: `scripts/test_*.py` は WebUI 起動時 auto-import で起動不能化する (2026-05-13 事故) → tests は `tests/` 配下強制

### Git 運用

`CLAUDE.md` で Git Flow (main/develop/feature/*) を採用。Claude は feature/* で作業し、main/develop への直接コミット禁止。

## ディレクトリ構成

```
.
├── .claude/skills/tdd-forge/SKILL.md      Claude に守らせる TDD/検証ルール (自作)
├── docs/                                   設計議論 (HTML) / 過去案 / ユーザー作業メモ
│   ├── README.md                           docs 目次
│   ├── phase8/                             Phase 8 責務分離 (refactoring_plan, c_design_choices 等)
│   ├── archive/                            過去の設計案 (現在の正本ではない)
│   ├── guides/                             ユーザー向け使い方ガイド
│   ├── images/                             ガイドから参照されるスクショ
│   └── user_memo/                          ユーザー手書きの修正案メモ
└── scripts/                                forge の scripts/ にそのまま置く
    ├── prompt_expander.py                  $変数展開
    ├── sd_variable_manager.html            変数管理 UI 本体
    ├── sd_variable_manager_modules/        UI JS モジュール群
    ├── sd_variable_presets.json            プリセット
    ├── vram_safe_batch.py                  v3 安定版 (現行)
    ├── vram_safe_batch_v3a.py              段階リファクタ履歴版
    ├── vram_safe_batch_v3b.py              段階リファクタ履歴版
    ├── vram_safe_batch_modules/            バッチ runner / job builder / VRAM 管理
    └── vram_recycler.py                    VRAM 段階開放
```

## セットアップ

### 前提

- [stable-diffusion-webui-forge](https://github.com/lllyasviel/stable-diffusion-webui-forge) がインストール済み
- CUDA 対応 GPU + PyTorch
- Python 3.10+ (forge 同梱の venv 推奨)

### インストール

```bash
# forge の scripts/ にコピー
cp -r scripts/* /path/to/stable-diffusion-webui-forge/scripts/

# (任意) tdd-forge skill を forge プロジェクトにも反映する場合
cp -r .claude/skills/tdd-forge /path/to/stable-diffusion-webui-forge/.claude/skills/
```

forge を再起動すると、Script ドロップダウンに「VRAM Safe Batch v3」、Always-On 拡張として「Prompt Expander」「SD Variable Manager」が現れる。

## 使い方 (概要)

### VRAM Safe Batch v3

1. メインプロンプト欄に `masterpiece, {1} {2}, 1girl, solo, {3}` のようにプレースホルダを書く
2. Script から「VRAM Safe Batch v3」を選択
3. 各リストスロットに 1 行 1 項目で値を入力 (`|<枚数>` で枚数指定)
4. Generate

途中で中断された場合、起動後に「前回の続きから再開する」にチェックを入れ、入力空のまま Generate で進捗ファイルから復元される。

### Prompt Expander

`vars/variables.json` に `char: ["alice", "bob"]` のように登録し、メインプロンプトに `$char` と書くと値で展開される。Batch Resume Script を選択していない通常生成でも効く。

### SD Variable Manager

WebUI の Always-On アコーディオンに表示される。変数の追加/編集/削除、テーマ切替、DnD、履歴管理を独自 UI で行う。

## 注意点

- `scripts/` 直下に **テスト/実行スクリプト** (`test_*.py`, `tmp_*.py`, `debug_*.py`) を置くと auto-import で WebUI が起動しなくなる。テストは forge の `tests/` 配下に置くこと
- `.pyc` キャッシュが残っていると古いコードが動く。移動/削除時は対応する `__pycache__/*.pyc` も消す
- CUDA fallback (CPU 動作になっていないか) は VERIFY 時に `device.type == 'cuda'` で確認すること (`tdd-forge` Skill 参照)

## ライセンス

MIT
