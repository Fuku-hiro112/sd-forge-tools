"""L1 unit tests — 通常生成の履歴保存・中断再開 / 再現性修正.

対象（すべて forge 非依存の純関数）:
  - history_v2.build_generation_dict   : generation dict 組立 (clip_skip 含む)
  - history_v2.apply_generation_to_p   : 復元 (clip_skip 含む = B1)。batch_runner.apply_resume_settings が委譲
  - history_v2.create_entry            : effective_negative / extensions 保存 (B2 / H4)
  - progress.compute_resume_slice      : 再開スライス (completed 枚スキップ + seed 継続)
  - progress.compute_completed         : iteration 基準カウント (A)
  - progress.should_count_iteration    : 同一 iteration の重複カウント防止 (ADetailer/Hires 対策)
  - expander.merge_variables_for_resume: inline > saved > json (回帰ガード、dd4f05c)

実行: python -m unittest tests.test_normal_gen_history -v
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from vram_safe_batch_modules import history_v2, progress, expander


def _stub_p(**overrides):
    """forge の processing オブジェクトの代わりに属性だけ持つスタブ."""
    base = dict(
        width=512, height=768, cfg_scale=7.0, steps=20,
        sampler_name="Euler a", scheduler="Karras",
        seed=1234, clip_skip=2,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


# ============================================================
#  B1 / Step1: generation dict は clip_skip を含む / 復元する
# ============================================================
class TestGenerationDict(unittest.TestCase):
    def test_build_generation_dict_includes_clip_skip(self):
        p = _stub_p(clip_skip=2)
        g = history_v2.build_generation_dict(p, "sequential", 1234)
        self.assertEqual(g["clip_skip"], 2)
        self.assertEqual(g["seed_mode"], "sequential")
        self.assertEqual(g["resolved_initial_seed"], 1234)
        self.assertEqual(g["width"], 512)
        self.assertEqual(g["sampler"], "Euler a")

    def test_apply_generation_to_p_restores_clip_skip(self):
        # B1: 保存した clip_skip が再開時に p へ戻ること（現状の欠落を検出）
        p = _stub_p(clip_skip=1)
        g = {"width": 640, "height": 960, "cfg_scale": 5.0, "steps": 30,
             "sampler": "DPM++ 2M", "scheduler": "Automatic",
             "resolved_initial_seed": 999, "seed_mode": "fixed", "clip_skip": 2}
        seed_mode, resolved = history_v2.apply_generation_to_p(p, g)
        self.assertEqual(p.clip_skip, 2)
        self.assertEqual(p.width, 640)
        self.assertEqual(p.steps, 30)
        self.assertEqual(seed_mode, "fixed")
        self.assertEqual(resolved, 999)
        self.assertEqual(p.seed, 999)

    def test_apply_generation_to_p_does_not_touch_extension_state(self):
        # 拡張設定(hr_* 等)には触れない (apply_resume_settings の不変条件を維持)
        p = _stub_p()
        p.enable_hr = True
        p.hr_scale = 2.0
        history_v2.apply_generation_to_p(p, {"width": 1024})
        self.assertTrue(p.enable_hr)
        self.assertEqual(p.hr_scale, 2.0)


# ============================================================
#  B2 / H4: create_entry は effective_negative / extensions を保存
# ============================================================
class TestCreateEntry(unittest.TestCase):
    def _gen(self):
        return {"width": 512, "height": 512, "cfg_scale": 7, "steps": 20,
                "sampler": "Euler a", "scheduler": "Karras",
                "initial_seed": 1, "resolved_initial_seed": 1,
                "seed_mode": "sequential", "clip_skip": 1}

    def test_create_entry_stores_effective_negative(self):
        # B2: 展開後ネガティブをスナップショット保存
        e = history_v2.create_entry(
            prompt_main="$char, masterpiece",
            prompt_negative="text",
            expansion_order=["char"],
            used_variables={"char": ["alice"]},
            generation=self._gen(),
            effective_negative="text, bad anatomy, low quality",
        )
        self.assertEqual(
            e["prompt"]["effective_negative"], "text, bad anatomy, low quality"
        )

    def test_create_entry_stores_extensions(self):
        # H4: 使用機能を記録
        e = history_v2.create_entry(
            prompt_main="$char",
            prompt_negative="",
            expansion_order=["char"],
            used_variables={"char": ["alice"]},
            generation=self._gen(),
            extensions={"hires": True, "vram_recycler": False, "source": "prompt_expander"},
        )
        self.assertEqual(e["extensions"]["hires"], True)
        self.assertEqual(e["extensions"]["source"], "prompt_expander")

    def test_create_entry_extensions_default_backward_compat(self):
        # extensions 未指定時は従来通り既定値（後方互換）
        e = history_v2.create_entry(
            prompt_main="x", prompt_negative="", expansion_order=[],
            used_variables={}, generation=self._gen(),
        )
        self.assertIn("vram_safe_batch", e["extensions"])
        # effective_negative 未指定なら空文字（再開時に再計算へフォールバック）
        self.assertEqual(e["prompt"].get("effective_negative", ""), "")


# ============================================================
#  Step3: 再開スライス（completed 枚スキップ + seed 継続）
# ============================================================
class TestComputeResumeSlice(unittest.TestCase):
    def test_sequential_skips_completed_and_continues_seed(self):
        expanded = ["p1", "p2", "p3", "p4"]
        prompts, seeds, n_iter = progress.compute_resume_slice(
            expanded, "sequential", 1000, completed=2
        )
        self.assertEqual(prompts, ["p3", "p4"])
        # compute_seed(sequential, 1000, global_num) = 1000 + (global_num-1)
        # 3 枚目 → 1002, 4 枚目 → 1003
        self.assertEqual(seeds, [1002, 1003])
        self.assertEqual(n_iter, 2)

    def test_fixed_uses_same_seed(self):
        expanded = ["p1", "p2", "p3"]
        prompts, seeds, n_iter = progress.compute_resume_slice(
            expanded, "fixed", 555, completed=1
        )
        self.assertEqual(prompts, ["p2", "p3"])
        self.assertEqual(seeds, [555, 555])
        self.assertEqual(n_iter, 2)

    def test_completed_zero_returns_full(self):
        expanded = ["p1", "p2"]
        prompts, seeds, n_iter = progress.compute_resume_slice(
            expanded, "sequential", 100, completed=0
        )
        self.assertEqual(prompts, ["p1", "p2"])
        self.assertEqual(seeds, [100, 101])
        self.assertEqual(n_iter, 2)

    def test_completed_ge_total_returns_empty(self):
        expanded = ["p1", "p2"]
        prompts, seeds, n_iter = progress.compute_resume_slice(
            expanded, "sequential", 100, completed=2
        )
        self.assertEqual(prompts, [])
        self.assertEqual(seeds, [])
        self.assertEqual(n_iter, 0)


# ============================================================
#  A: iteration 基準カウント（ADetailer/Hires の過剰カウント防止）
# ============================================================
class TestProgressCount(unittest.TestCase):
    def test_compute_completed_fresh(self):
        # 新規生成: offset 0, iteration 0-origin → completed は 1-origin
        self.assertEqual(progress.compute_completed(0, 0), 1)
        self.assertEqual(progress.compute_completed(0, 4), 5)

    def test_compute_completed_resume_offset(self):
        # 再開: offset=2 から、最初の新規 iteration(0) は通算 3 枚目
        self.assertEqual(progress.compute_completed(2, 0), 3)
        self.assertEqual(progress.compute_completed(2, 3), 6)

    def test_should_count_iteration_dedup(self):
        # 同じ iteration は 1 回しか数えない（ADetailer/Hires が複数 image を返しても）
        counted = set()
        self.assertTrue(progress.should_count_iteration(counted, 0))
        counted.add(0)
        self.assertFalse(progress.should_count_iteration(counted, 0))
        self.assertTrue(progress.should_count_iteration(counted, 1))


# ============================================================
#  回帰ガード: merge_variables_for_resume (dd4f05c)
# ============================================================
class TestMergePriority(unittest.TestCase):
    def test_inline_over_saved_over_json(self):
        inline = {"a": ["i"]}
        saved = {"a": ["s"], "b": ["s"]}
        json_vars = {"a": ["j"], "b": ["j"], "c": ["j"]}
        m = expander.merge_variables_for_resume(inline, saved, json_vars)
        self.assertEqual(m["a"], ["i"])   # inline 最優先
        self.assertEqual(m["b"], ["s"])   # saved > json
        self.assertEqual(m["c"], ["j"])   # 欠落ネストを json が補完


if __name__ == "__main__":
    unittest.main()
