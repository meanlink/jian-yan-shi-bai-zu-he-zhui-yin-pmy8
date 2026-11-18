"""旧仪器部分单项数据 + 共败三分类的独立单元测试（仅标准库）。

运行：cd backend && python -m unittest discover -s ../test-artifacts/gb-1012/tests
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [
    os.path.abspath(os.path.join(HERE, "..", "..", "..", "workspace", "backend")),
    os.path.abspath(os.path.join(HERE, "..", "..", "backend")),
]
BACKEND_DIR = next((path for path in CANDIDATES if os.path.isfile(os.path.join(path, "src", "services", "business.py"))), CANDIDATES[-1])
sys.path.insert(0, BACKEND_DIR)

from src.constants.assay import ITEMS  # noqa: E402
from src.services import legacy, uncertain, partial_runner  # noqa: E402


def row(batch_id, total, **bits):
    base = {"batch_id": batch_id, "fail_total": total}
    for key in ITEMS:
        if key in bits:
            base[key] = bits[key]
    return row_default_unknown(base)


def row_default_unknown(base):
    return base


class LegacyValidationTests(unittest.TestCase):
    def test_accepts_feasible_partial_rows(self):
        rows = [
            {"batch_id": "B1", "fail_total": 2, "heat_fail": 1, "ph_fail": 0},
            {"batch_id": "B2", "fail_total": 0, "heat_fail": 0, "ph_fail": 0, "viscosity_fail": 0},
            {"batch_id": "B3", "fail_total": 5, "heat_fail": 1, "ph_fail": 1, "viscosity_fail": 1, "ash_fail": 1, "color_fail": 1},
        ]
        normalized = legacy.normalize_legacy_records(rows)
        self.assertEqual(len(normalized), 3)
        # B1: 3 个未知项选 1 个失败 => 3 种补全
        self.assertEqual(len(normalized[0]["options"]), 3)
        for assignment in normalized[0]["options"]:
            full = legacy.completion_to_row(normalized[0], assignment)
            self.assertEqual(sum(full[k] for k in ITEMS), 2)

    def test_rejects_known_failures_above_total(self):
        rows = [{"batch_id": "B9", "fail_total": 1, "heat_fail": 1, "ph_fail": 1}]
        with self.assertRaisesRegex(ValueError, "B9"):
            legacy.normalize_legacy_records(rows)

    def test_rejects_total_requiring_more_unknown_than_available(self):
        # 已知 0 失败，未知仅 2 项，总数却要 4
        rows = [{"batch_id": "B7", "fail_total": 4, "heat_fail": 0, "ph_fail": 0, "viscosity_fail": 0}]
        with self.assertRaisesRegex(ValueError, "B7"):
            legacy.normalize_legacy_records(rows)

    def test_rejects_non_binary_marker(self):
        rows = [{"batch_id": "B4", "fail_total": 1, "heat_fail": 2}]
        with self.assertRaisesRegex(ValueError, "B4"):
            legacy.normalize_legacy_records(rows)

    def test_rejects_out_of_range_total(self):
        rows = [{"batch_id": "B5", "fail_total": 6, "heat_fail": 1}]
        with self.assertRaisesRegex(ValueError, "B5"):
            legacy.normalize_legacy_records(rows)

    def test_rejects_missing_total_and_duplicate_batch(self):
        with self.assertRaisesRegex(ValueError, "B6"):
            legacy.normalize_legacy_records([{"batch_id": "B6", "heat_fail": 1}])
        rows = [
            {"batch_id": "B8", "fail_total": 1, "heat_fail": 1},
            {"batch_id": "B8", "fail_total": 2, "ph_fail": 0},
        ]
        with self.assertRaisesRegex(ValueError, "B8"):
            legacy.normalize_legacy_records(rows)

    def test_rejects_when_all_items_unknown(self):
        rows = [{"batch_id": "B10", "fail_total": 2}]
        with self.assertRaisesRegex(ValueError, "B10"):
            legacy.normalize_legacy_records(rows)

    def test_empty_string_treated_as_unknown(self):
        rows = [{"batch_id": "B11", "fail_total": 1, "heat_fail": 1, "ph_fail": ""}]
        normalized = legacy.normalize_legacy_records(rows)
        self.assertIn("ph_fail", normalized[0]["unknown_keys"])

    def test_ground_truth_is_always_a_feasible_completion(self):
        """由完整真值退化出的部分数据，真值补全必须在可行补全集合内。"""
        import random
        rng = random.Random(2026)
        raw = []
        truths = {}
        for i in range(60):
            truth = {k: rng.randint(0, 1) for k in ITEMS}
            truths[f"G{i:03}"] = dict(truth)
            total = sum(truth.values())
            kept = rng.sample(ITEMS, rng.randint(1, 4))
            raw.append({
                "batch_id": f"G{i:03}",
                "fail_total": total,
                **{k: (truth[k] if k in kept else None) for k in ITEMS},
            })
        normalized = legacy.normalize_legacy_records(raw)
        for source in normalized:
            original_truth = truths[source["batch_id"]]
            truth_assignment = {k: original_truth[k] for k in source["unknown_keys"]}
            self.assertIn(truth_assignment, source["options"])


def deterministic_partial_dataset(n=40):
    """构造结构可控的部分数据：制样共败(heat+viscosity)在多数批同时失败。"""
    rows = []
    for i in range(n):
        prep = i % 5 < 3  # 60% 批进入制样异常
        if prep:
            bits = {"heat_fail": 1, "viscosity_fail": 1, "ph_fail": 1 if i % 2 else 0}
            total = 2 + bits["ph_fail"] + (1 if i % 4 == 0 else 0)
        else:
            bits = {"heat_fail": 0, "viscosity_fail": 0, "ph_fail": 0}
            total = 1 if i % 7 == 0 else 0
        # 保留部分单项未知：ash/color 总是未知，偶尔藏起 ph
        if i % 3 == 0:
            bits.pop("ph_fail", None)
        rows.append({"batch_id": f"HP-P{i+1:03}", "fail_total": total, **bits})
    return rows


def exhaustive_counts(rows, antecedent, consequent):
    """无剪枝全状态 DP（测试专用），独立对照生产代码的 Pareto 前沿剪枝。"""
    states = {(0, 0, 0)}
    for row in rows:
        nxt = set()
        for j, sa, sb in states:
            for assignment in row["options"]:
                values = dict(row["known"])
                values.update(assignment)
                has_a = all(values[k] == 1 for k in antecedent)
                has_b = all(values[k] == 1 for k in consequent)
                nxt.add((
                    j + (1 if has_a and has_b else 0),
                    sa + (1 if has_a else 0),
                    sb + (1 if has_b else 0),
                ))
        states = nxt
    return states


class UncertainEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = legacy.normalize_legacy_records(deterministic_partial_dataset())

    def test_dataset_shape_and_completion_enumeration(self):
        self.assertEqual(len(self.rows), 40)
        for normalized in self.rows:
            self.assertGreaterEqual(len(normalized["options"]), 1)
            for assignment in normalized["options"]:
                full = legacy.completion_to_row(normalized, assignment)
                self.assertEqual(sum(full[k] for k in ITEMS), normalized["fail_total"])
                self.assertTrue(all(full[k] in (0, 1) for k in ITEMS))

    def test_candidate_rule_scope_matches_business_scope(self):
        rules = uncertain.generate_candidate_rules()
        # 2 项集: C(5,2)*2 = 20；3 项集: C(5,3)*6 = 60；合计 80，正反向独立
        self.assertEqual(len(rules), 80)
        keys = {uncertain._rule_key(a, b) for a, b in rules}
        self.assertEqual(len(keys), 80)
        for a, b in rules:
            self.assertLessEqual(len(a | b), 3)
            self.assertTrue(a.isdisjoint(b))

    def test_judgments_partition_all_candidates_and_verdicts(self):
        result = uncertain.analyze_partial(self.rows, {"min_support": 0.05, "min_confidence": 0.2})
        self.assertEqual(result["kind"], "partial")
        judgments = result["judgments"]
        self.assertEqual(len(judgments), 80)
        self.assertEqual(
            len(judgments),
            sum(len(result["groups"][v]) for v in ("certain", "possible", "impossible")),
        )
        self.assertTrue(all(j["verdict"] in ("certain", "possible", "impossible") for j in judgments))

    def test_possible_rules_carry_both_witnesses_and_they_are_feasible(self):
        result = uncertain.analyze_partial(self.rows, {"min_support": 0.05, "min_confidence": 0.2})
        possible = result["groups"]["possible"]
        self.assertGreater(len(possible), 0)
        for judgment in possible:
            pw, fw = judgment["pass_witness"], judgment["fail_witness"]
            self.assertEqual(len(pw["completions"]), 40)
            self.assertEqual(len(fw["completions"]), 40)
            self._assert_witness_feasible(pw)
            self._assert_witness_feasible(fw)
            # 入选见证必须过阈值，落选见证必须不过
            self.assertGreater(pw["lift"], 1.0)
            self.assertTrue(pw["support_pct"] >= 5 - 1e-9 and pw["confidence_pct"] >= 20 - 1e-9)
            self.assertTrue(
                fw["lift"] <= 1.0 + 1e-9 or fw["support_pct"] < 5 - 1e-9
                or fw["confidence_pct"] < 20 - 1e-9
            )

    def _assert_witness_feasible(self, witness):
        rows_by_id = {r["batch_id"]: r for r in self.rows}
        for completion in witness["completions"]:
            source = rows_by_id[completion["batch_id"]]
            # 已知项不可被补全篡改
            for key, bit in source["known"].items():
                self.assertEqual(completion[key], bit)
            # 补全后失败总数必须等于旧仪器总数
            self.assertEqual(sum(completion[k] for k in ITEMS), source["fail_total"])

    def test_witness_metrics_match_counts(self):
        result = uncertain.analyze_partial(self.rows, {"min_support": 0.05, "min_confidence": 0.2})
        witness = result["groups"]["possible"][0]["pass_witness"]
        self.assertEqual(round(witness["counts"]["joint"] / 40 * 100, 2), witness["support_pct"])

    def test_certain_rule_holds_under_every_reachable_state(self):
        result = uncertain.analyze_partial(self.rows, {"min_support": 0.05, "min_confidence": 0.2})
        for judgment in result["groups"]["certain"]:
            a = frozenset(judgment["antecedent_keys"])
            b = frozenset(judgment["consequent_keys"])
            states = exhaustive_counts(self.rows, a, b)
            self.assertTrue(all(uncertain._passes(state, 40, 0.05, 0.2) for state in states))
            self.assertEqual(len(judgment["certain_completion"]), 40)

    def test_impossible_rule_fails_under_every_reachable_state(self):
        result = uncertain.analyze_partial(self.rows, {"min_support": 0.05, "min_confidence": 0.2})
        for judgment in result["groups"]["impossible"]:
            a = frozenset(judgment["antecedent_keys"])
            b = frozenset(judgment["consequent_keys"])
            states = exhaustive_counts(self.rows, a, b)
            self.assertTrue(all(not uncertain._passes(state, 40, 0.05, 0.2) for state in states))

    def test_frontier_pruning_matches_exhaustive_dp_for_all_rules(self):
        """40 批 × 80 条规则：剪枝后的三分类必须与无剪枝全状态 DP 完全一致。"""
        params = {"min_support": 0.05, "min_confidence": 0.2}
        result = uncertain.analyze_partial(self.rows, params)
        for judgment in result["judgments"]:
            a = frozenset(judgment["antecedent_keys"])
            b = frozenset(judgment["consequent_keys"])
            states = exhaustive_counts(self.rows, a, b)
            passes = [uncertain._passes(s, 40, 0.05, 0.2) for s in states]
            expected = "certain" if all(passes) else ("impossible" if not any(passes) else "possible")
            self.assertEqual(judgment["verdict"], expected, judgment["rule_key"])

    def test_exhaustive_global_completion_agrees_with_dp(self):
        """小规模数据：暴力枚举全部全局补全，验证 DP 三分类完全一致。"""
        import itertools
        small = legacy.normalize_legacy_records(deterministic_partial_dataset(8))
        _, _, _, judgments, _ = uncertain.classify_rules(small, {"min_support": 0.05, "min_confidence": 0.2})
        option_grid = [list(range(len(r["options"]))) for r in small]
        total = len(small)
        for judgment in judgments:
            a = frozenset(judgment["antecedent_keys"])
            b = frozenset(judgment["consequent_keys"])
            passes = []
            for path in itertools.product(*option_grid):
                j = sa = sb = 0
                for row_data, idx in zip(small, path):
                    values = dict(row_data["known"])
                    values.update(row_data["options"][idx])
                    has_a = all(values[k] == 1 for k in a)
                    has_b = all(values[k] == 1 for k in b)
                    j += 1 if has_a and has_b else 0
                    sa += 1 if has_a else 0
                    sb += 1 if has_b else 0
                passes.append(uncertain._passes((j, sa, sb), total, 0.05, 0.2))
            expected = "certain" if all(passes) else ("impossible" if not any(passes) else "possible")
            self.assertEqual(judgment["verdict"], expected, judgment["rule_key"])
        self.assertEqual(len(judgments), 80)

    def test_fully_known_data_degrades_to_deterministic_verdicts(self):
        import random
        rng = random.Random(11)
        rows = []
        for i in range(40):
            truth = {k: rng.randint(0, 1) for k in ITEMS}
            rows.append({"batch_id": f"F{i:03}", "fail_total": sum(truth.values()), **truth})
        normalized = legacy.normalize_legacy_records(rows)
        self.assertTrue(all(not r["unknown_keys"] and len(r["options"]) == 1 for r in normalized))
        result = uncertain.analyze_partial(normalized, {"min_support": 0.05, "min_confidence": 0.2})
        # 无未知项 => 不存在歧义，possible 必须为空
        self.assertEqual(len(result["groups"]["possible"]), 0)
        # 逐规则用补全后的完整事务直接核算，certain 必须与阈值判据逐一吻合
        for judgment in result["judgments"]:
            a = frozenset(judgment["antecedent_keys"])
            b = frozenset(judgment["consequent_keys"])
            j = sa = sb = 0
            for row in normalized:
                values = dict(row["known"])
                ha = all(values[k] == 1 for k in a)
                hb = all(values[k] == 1 for k in b)
                j += 1 if ha and hb else 0
                sa += 1 if ha else 0
                sb += 1 if hb else 0
            direct = uncertain._passes((j, sa, sb), 40, 0.05, 0.2)
            self.assertEqual(judgment["verdict"] == "certain", direct, judgment["rule_key"])
        with self.assertRaisesRegex(ValueError, "支持度"):
            uncertain.analyze_partial(self.rows, {"min_support": 0.9, "min_confidence": 0.65})

    def test_too_few_batches_rejected(self):
        small = legacy.normalize_legacy_records(deterministic_partial_dataset(30)[:10])
        with self.assertRaisesRegex(ValueError, "30批"):
            uncertain.analyze_partial(small, {})


class PartialRunnerResumeTests(unittest.TestCase):
    def setUp(self):
        self.rows = deterministic_partial_dataset()
        self.params = {"min_support": 0.05, "min_confidence": 0.2}
        self.candidate_keys = [
            uncertain._rule_key(a, b) for a, b in uncertain.generate_candidate_rules()
        ]

    def test_full_run_judges_every_rule_once(self):
        stored = {}
        rule_keys, newly = partial_runner.run_partial_engine(
            self.rows, self.params, set(),
            lambda seq, key, jd: stored.__setitem__(key, jd),
        )
        self.assertEqual(newly, 80)
        self.assertEqual(len(stored), 80)
        self.assertEqual(sorted(stored), sorted(self.candidate_keys))

    def test_resume_skips_done_rules_and_completes(self):
        # 模拟中断：先登记前 35 条
        stored = {}
        partial_runner.run_partial_engine(
            self.rows, self.params, set(self.candidate_keys[35:]),
            lambda seq, key, jd: stored.__setitem__(key, jd),
        )
        first_batch = dict(stored)
        self.assertEqual(len(first_batch), 35)
        done = set(first_batch)

        # 续跑：只补剩余 45 条，不重复已判规则
        added = []
        rule_keys, newly = partial_runner.run_partial_engine(
            self.rows, self.params, done,
            lambda seq, key, jd: added.append(key),
        )
        self.assertEqual(newly, 45)
        self.assertFalse(set(added) & done)
        self.assertEqual(set(added) | done, set(rule_keys))

    def test_retry_with_all_done_registers_nothing(self):
        stored = {}
        partial_runner.run_partial_engine(
            self.rows, self.params, set(),
            lambda seq, key, jd: stored.__setitem__(key, jd),
        )
        added = []
        _, newly = partial_runner.run_partial_engine(
            self.rows, self.params, set(stored), lambda *a: added.append(a)
        )
        self.assertEqual(newly, 0)
        self.assertEqual(added, [])

    def test_pending_sequences_matches_resume_point(self):
        done = set(self.candidate_keys[:10])
        pending = partial_runner.pending_sequences(80, done, self.candidate_keys)
        self.assertEqual(pending, list(range(10, 80)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
