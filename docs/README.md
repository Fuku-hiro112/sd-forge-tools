# docs/ — ドキュメント目次

このディレクトリは stable-diffusion-webui-forge のカスタム拡張群 (vram_safe_batch v3b → Phase 8 で分割された 4 拡張) の設計・実装ドキュメントを格納する。

## ディレクトリ構成

```
docs/
├── README.md                  ← このファイル
├── phase8/                    Phase 8 (責務分離) 関連
├── archive/                   過去の設計ドキュメント (参考用、現状の正本ではない)
├── guides/                    ユーザー向けガイド
├── images/                    スクリーンショット
└── user_memo/                 ユーザー個人メモ
```

## phase8/ — Phase 8 責務分離 (2026-05 完了)

`vram_safe_batch_v3b.py` (1075 行モノリス) を 4 つの独立拡張に分割した一連の作業。

| ファイル | 用途 | 読者 |
|---|---|---|
| [`refactoring_plan.html`](phase8/refactoring_plan.html) | Phase 8 全体の設計図 (ユーザー承認用) | ユーザー / レビュアー |
| [`implementation_playbook.md`](phase8/implementation_playbook.md) | Claude 実装エージェント用詳細プレイブック (機能 ID / 不変条件 / 各 Phase 手順) | Claude / 実装者 |
| [`c_design_choices.html`](phase8/c_design_choices.html) | Phase 8-C の 3 設計案 (保守/標準/攻め) の比較 | ユーザー (選択時) |
| [`c_ui_restructure.html`](phase8/c_ui_restructure.html) | Phase 8-C-UI 大規模 UI 移管の事前合意ドキュメント | ユーザー (承認用) |

### 達成された責務分離 (Phase 8 後の構成)
- `scripts/prompt_expander.py` (AlwaysOn): `$変数` 展開 / 展開順 UI / variables 同期 API / SSE
- `scripts/vram_recycler.py` (AlwaysOn): 画像ごと VRAM 解放 (トグル)
- `scripts/batch_resume.py` (Script): 履歴 v2 / 中断再開
- `scripts/text_replace.py` (AlwaysOn): Ctrl+F 検索置換パネル
- `scripts/vram_safe_batch_v3b.py`: deprecation スタブ (1 週間程度残置後に削除予定)

ロールバック地点: `git tag --list 'phase-*'`

## archive/ — 過去の設計ドキュメント

現在のコードベースの **正本ではない** が、設計判断の経緯を追うための参考資料。

| ファイル | 概要 |
|---|---|
| `hotfix3_event_loop_design.html` | `_register_api` 内の `asyncio.create_task` → `app.on_event("startup")` 切替の経緯 |
| `variable_manager_sync_design.html` | Variable Manager 双方向同期 (Phase B) の設計 |
| `vram_safe_batch_redesign.html` / `.md` | Phase 8 以前の v3b リファクタ計画 (現在は Phase 8 で実現済み) |

## guides/ — ユーザー向けガイド

| ファイル | 概要 |
|---|---|
| `extensions_guide.html` | Forge 拡張機能 (ADetailer / Hires.fix / sd-forge-couple / 他) の使い方ガイド |

## images/ — スクリーンショット

`guides/extensions_guide.html` から参照される画像群。

## user_memo/ — ユーザー個人メモ

ユーザーが手書きで残した修正案などの作業メモ。ドキュメントとしての完成度よりも作業ログとしての保存が目的。
