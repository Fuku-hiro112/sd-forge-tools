---
name: tdd-forge
description: Use this skill for code changes in stable-diffusion-webui-forge. Enforces Pre-flight → RED → GREEN → REFACTOR → VERIFY with tiered verification (L1 unit, L2 UI, L3 GPU). Skip TDD only for non-functional changes (docs, comments, log strings, renames). RED must fail for the right reason. L3 must confirm CUDA isn't silently falling back to CPU. No exception-swallowing in GREEN. Large refactors and L2/L3 user-reported bug fixes MUST delegate VERIFY to a separate sub-agent (blind verification).
---

# tdd-forge — stable-diffusion-webui-forge 専用 TDD ワークフロー

本 Skill は当プロジェクト固有の制約 (Python + JS/HTML、`scripts/` 配下 auto-import 事故、venv 経由 python、Gradio/Forge UI、CUDA fallback 罠) を踏まえた TDD ルール。汎用的な `tdd-workflow` skill では拾えないプロジェクト固有の落とし穴に対処する。

## 1. 発動条件 / スキップ条件

**適用**: 機能追加、バグ修正、リファクタ、API 変更、UI 変更、テスト追加。

**スキップ可 (TDD 不要)**:
- コメント修正のみ
- ドキュメント (README, *.md) のみ
- ログ/エラー文言のみ (動作変更なし)
- 機能変更を伴わない rename のみ
- フォーマット/インデントのみ

判定基準: 「ユーザーから見える振る舞いが変わるか?」NO ならスキップ可。スキップする場合はその旨を一言伝える。

## 2. 5 フェーズサイクル

### Phase 0: Pre-flight (実装理解) — 必須

RED テストを書く前に、必ず以下を実施:

- 修正対象とその直接の呼び出し元 / 被呼び出し関数を `Read` で実体確認 (推測で書かない)
- バグ修正の場合: ユーザー報告のエラー文を該当箇所で実際に再現 (思考だけで再現済み扱いにしない)
- 既存テストが該当機能をカバーしているか `Grep` で確認 (重複テスト回避)
- 1 行報告: 「(関連ファイル) を読み、(振る舞い X) を確認した」

これを省くと "周辺を読まずに局所 patch" の失敗パターンに直行する。

### Phase 1: RED

- 失敗するテストを `tests/test_<scope>.py` に作成し実行
- **正しい理由で失敗していること**:
  - 無効: `ImportError`, `SyntaxError`, `ModuleNotFoundError`, fixture 失敗、無関係 assertion
  - 有効: 修正対象の振る舞いが期待値と異なる、再現エラーがそのまま発生
- **修正前ログを保存 / 引用**: failing assertion メッセージ or 例外スタックを完了報告に含める。「本当に再現したか / 別エラーで落ちていないか」追跡用

### Phase 2: GREEN

- テストを通す **最小** 変更
- **禁止リスト** (実害のあった失敗パターン):
  - hardcode 値での回避 / test-only branch (`if testing:` / `if env == "test":`)
  - monkey patch
  - **例外握り潰し** (`try: ... except: pass` / `except Exception: pass`) — テストは通るが本番で silent failure
  - 「とりあえず None を返す」「とりあえず空配列」で型だけ合わせる
- public API / シグネチャを変える場合は §3 grep 範囲をすべて実行してから

### Phase 3: REFACTOR

- テスト緑を維持して整理
- **上限を遵守**:
  - テスト対象とその直接の周辺ファイルに限定
  - 無関係ファイルを触らない
  - architecture rewrite / 大規模 rename / 命名規則一括変更は別タスク
  - 「ついでに」の改善は次タスクへ繰り越す

### Phase 4: VERIFY

- §5 の Verify Levels に従って実行確認
- §13 該当案件では Verifier sub-agent に委譲

## 3. grep 範囲 (重要 — 重複定義事故の再発防止)

修正対象が関数 / 変数の場合、以下すべてを必ず確認:

- 修正ファイル自身
- 呼び出し元 (関数名の参照)
- export / import (CommonJS, ES Module, Python `from`)
- イベントリスナー登録 (`addEventListener`, `on*`, Gradio の event binding)
- HTML 側参照 (`onclick=`, `id="..."` 経由の DOM 取得)
- 動的呼び出し (`window[name]`, `getattr`, `globals()[name]`)

JS 修正で特に重要。本プロジェクトでは render.js / events.js / themes.js / ui-ops.js を横断検索が基本。

## 4. テスト品質

### 4.1 Assertion の質

- 弱い (NG): `assertIsNotNone(x)`、`self.assertTrue(result)`、「クラッシュしないこと」だけの assert
- 強い (OK): 入力 → 期待出力を具体的に記述

```python
# NG
self.assertIsNotNone(result)
# OK
self.assertEqual(result.shape, (1, 231, 2048))
self.assertTrue(torch.all(result[:, 77:, :] == 0.0))
```

振る舞いを具体的に検証する。可能なら入力 → 出力を明示。

### 4.2 テストの最小性

- **1 test = 1 振る舞い** (1 assertion とは限らないが、責務は 1 つ)
- fixture / setUp は最小化。複数テストで使い回すのは OK だが、巨大化したら分割
- 不要な mock を追加しない。本物が使えるなら本物
- 1 テストメソッドが 30 行を超えたら設計を疑う

## 5. Verify Levels

| Level | 対象 | 必須動作 |
|---|---|---|
| **L1** | バックエンドロジック、純粋関数、ユーティリティ | unittest 実行 + 以前のエラー文を grep で再確認 (消えているか) |
| **L2** | UI / DOM / CSS / イベントハンドラ | L1 + §6 の UI 検証手順 |
| **L3** | CUDA カーネル、画像生成、メモリ管理、ファイル I/O | L1 + §7 の GPU 検証手順 |

判定:
- `*.py` (backend/, modules/) → L1、CUDA touch なら L3
- `scripts/*.html`, `scripts/sd_variable_manager_modules/*.js` → L2
- `backend/diffusion_engine/*.py`, `backend/nn/*.py`, `modules/sd_samplers*.py` → L3

## 6. L2 — UI 検証手順

**スクリーンショット撮影だけでも、evaluate 戻り値だけでも不十分**。両輪で検証:

1. **DOM + 視覚 + インタラクション** をすべて確認:
   - DOM 状態を `evaluate()` で取得 (要素の存在、computed style、属性)
   - **加えて** screenshot を Read して視覚確認 — `evaluate()` の戻り値だけで「OK」と報告しない
2. **見える ≠ 動く** の罠を避ける:
   - `_click` でハンドラを起動
   - クリック後の state 変化 (storage / DOM 属性 / class) を確認
   - 連動する別 UI (テーマ反映色など) も変化しているか確認
3. **完了報告に含める** (5 項目):
   1. 期待 UI 要素名 (例: "Theme picker grid")
   2. 画面上の位置 (例: "Theme ボタン直下、y=55 付近")
   3. 状態 (active / hidden / disabled / "10 件のテーマカードがすべて表示")
   4. 修正前との差分 ("以前は何も表示されなかったが今は X が見える")
   5. インタラクション結果 (click → state change の観測)
4. **flake 対策**:
   - 固定 `sleep` に依存しない
   - DOM 条件待ち (`browser_wait_for`、`waitForSelector`、polling) を優先
   - キャッシュで古い JS が動いていないか確認 (ポート変更 / `?nocache=`)

## 7. L3 — CUDA / GPU 検証手順

「画像生成できた = OK」は不十分:

1. **CUDA が実際に使われているログを確認**:
   - WebUI 起動ログに `Device: cuda` 等の出力
   - 関連 tensor の `.device.type == 'cuda'` を assert
   - `nvidia-smi` で VRAM 使用量が増えること
2. **CPU fallback していないこと**:
   - `torch.cuda.is_available()` が True
   - 生成中に CPU 使用率が突出しない (silent fallback の症状)
3. **VRAM leak — 現実的な検出方法** (PyTorch の cache allocator / lazy release を考慮):
   - 単発の `memory_allocated()` 前後差で判定 **しない** (cache のため誤検知多発)
   - **連続実行で蓄積しないことを確認**: 同じ生成を 3 回繰り返し、VRAM 使用量が単調増加しないこと
   - 増加が見られた場合のみ精査
4. **precision mismatch**:
   - dtype 期待値 (fp16 / bf16 / fp8) と実際の `tensor.dtype` を一致確認
5. **生成画像 1 枚は最低成果物**:
   - 視覚的破綻 (黒画像、ノイズ画像、極端な色化け) していないこと

## 8. Python テスト雛形

```python
# tests/test_<feature>.py
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

class TestX(unittest.TestCase):
    def test_specific_behavior(self):
        result = target_function(input_value)
        self.assertEqual(result, expected_value)
```

実行:
- 通常: `python -m unittest tests.test_<feature> -v`
- torch を import する場合: `./venv/Scripts/python.exe -m unittest tests.test_<feature> -v`

## 9. JS / HTML テスト雛形

JS のテストランナーは未導入。**Python から静的解析で代用**:

```python
def test_function_is_defined(self):
    src = open("scripts/sd_variable_manager_modules/render.js").read()
    self.assertRegex(src, r"function\s+myFunc\s*\(")
```

動的検証は **Playwright MCP の `evaluate()` で関数を実行して戻り値を assert** + screenshot で視覚確認 (両方)。

## 10. ファイル配置厳守

**禁止**:
- `scripts/test_*.py` (auto-import で起動不能化、2026-05-13 事故)
- プロジェクト root 直下の `test_*.py` / `tmp_test.py` / `debug_*.py` / `scratch_*.py`
- 任意ディレクトリの `tmp_*.py` / `debug_*.py`

**配置先**: `tests/` 配下のみ。命名は `test_<scope>.py`。

## 11. Anti-patterns

| アンチパターン | 対策 |
|---|---|
| Unit test passes ≠ 機能動作 | L3 で実生成 |
| テストを書いただけで実行していない | RED で必ず実行ログを残す |
| `mcp__playwright__browser_navigate` だけで確認終了 | クリック → evaluate or screenshot まで |
| evaluate() の戻り値だけ確認して screenshot 撮らない | §6 の両輪検証 |
| ユーザー報告のエラーログを再確認していない | エラー文 grep を 1 度実行 |
| モックだけ通して実環境未確認 | L2 / L3 でモック以外も走らせる |
| 重複関数定義 (toggleThemePicker @ render.js + themes.js) | §3 全モジュール grep |
| scripts/ 直下にテストや実行スクリプト | tests/ 強制 |
| キャッシュで古い JS が動いて検証が無効 | ポート変更 or `?nocache=` |
| 修正後に古いテスト結果を引用 | 再実行コマンドの出力を引用 |
| unittest 実行対象を間違えている | `-v` でモジュール名と test 数を確認 |
| evaluate() の戻り値を確認していない | 戻り値を変数に受け文章で報告 |
| screenshot path を間違えて別画像を見ている | 撮影直後の path を Read |
| grep の結果 0 件なのに「確認済み」と報告 | 0 件は調査未完。範囲変更 |
| RED が `ImportError` で「失敗した」 | §2 Phase 1 の正しい理由 |
| REFACTOR でスコープクリープ | §2 Phase 3 上限 |
| `except: pass` / `except Exception: pass` で GREEN | §2 Phase 2 禁止リスト |
| 弱い assertion (`assertIsNotNone` のみ) | §4.1 強い assertion |
| 周辺を読まずに局所 patch | §2 Phase 0 Pre-flight |
| PyTorch memory_allocated 単発差分で leak 判定 | §7-3 連続実行で蓄積判定 |
| 固定 sleep に依存した flaky test | §6-4 DOM 条件待ち |
| 自分で実装 → 自分で OK 判定 (大規模改修) | §13 Verifier 分離 |

## 12. 既存リソース参照

- 良い実例: `tests/test_sdxl_cond_padding.py` (L3 案件), `tests/test_theme_picker_toggle.py` (L2 案件)
- Playwright tools: `mcp__playwright__browser_navigate / _click / _evaluate / _take_screenshot / _wait_for`
- プロジェクトルール: `CLAUDE.md` (`scripts/` 直下 NG), `../CLAUDE.md` (Git Flow)

## 13. Sub-agent / Verifier 分離 — 自己検証バイアス対策

実装した本人が「直りました」と判断すると、確証バイアス・見落とし・テスト不正合のリスクが高い。一定条件下で **VERIFY を別 sub-agent (Explore or general-purpose) に委譲** する。

### 13.1 分離が必須なケース

- **L2 案件のうち**、ユーザー報告の不具合修正 (例: "クリックしても何も表示されない")
- **L3 案件全般** (CUDA / メモリ / 生成パイプライン)
- **大規模改修** — 以下のいずれかに該当する場合は L レベルに関わらず必須:
  - 3 ファイル以上に跨る修正
  - 単一ファイルでも 100 行以上の追加・変更
  - public API / 関数シグネチャの変更を伴う
  - 複数モジュール (例: themes.js + render.js + events.js + html) を横断する修正
  - 新規 Skill / 新規拡張スクリプトの追加
  - リファクタ目的で既存ロジックを移動・分割するもの

軽微な修正 (typo, ログ文言, スキップ条件該当) は不要。L1 単体テストのみで完結する純粋関数 (1 ファイル / 数十行以内) も不要。

**判定が迷うとき**: 「自分の修正方針が間違っていた場合、ユーザーに見せる前に気付ける自信があるか?」NO ならば Verifier を使う。

### 13.2 ハンドオフ・テンプレート (実装者 → Verifier)

実装者が Verifier に渡す情報は **以下に限定** (実装の中身は渡さない):

```
[症状] ユーザー報告の原文 (引用)
[再現手順] 起動コマンド / URL / 操作シーケンス
[期待する観測] 何が見えれば直っていると判定するか (具体的に)
[期待しない観測] 残っていたら NG な状態 (元のエラー文、空表示など)
[テスト対象 path] 触ったファイルの一覧のみ (差分は渡さない)
```

実装ロジック・修正方針・新規関数名などを渡すと Verifier が同じバイアスで検証してしまう。**blind verification** を維持する。

### 13.3 Verifier の作法

- 渡されたテスト対象 path を `Read` で **現状** を確認
- 期待する観測 / しない観測の両方を独立に検証
- L2: 必ず `evaluate()` + `take_screenshot` + Read で視覚確認
- L3: `device.type`, 連続実行 VRAM 推移, 画像視認
- 判定は次の 3 値のみ: `RESOLVED` / `UNRESOLVED` / `INCONCLUSIVE`
- 各判定には観測ログ (実コマンド出力、screenshot path、戻り値) を必ず添付

### 13.4 結果の取り扱い

- `RESOLVED` → 完了報告に Verifier ログを引用して終了
- `UNRESOLVED` → **実装者は自動リトライしない**。ユーザーに Verifier の所見を提示し、追加情報・方針を仰ぐ
- `INCONCLUSIVE` (環境問題・到達不能) → ユーザーに環境確認を依頼

### 13.5 やってはいけないこと

- 同一 Agent ターン内で「自分で実装 → 自分で OK 判定」して終了 (§13.1 該当時)
- Verifier に "ここを見れば直っているはず" と誘導する (blind 性が壊れる)
- Verifier が `UNRESOLVED` を返したのに実装者が「環境のせい」と判断して完了報告
