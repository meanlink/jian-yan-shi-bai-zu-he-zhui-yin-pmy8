"""部分单项结果下的共败规则三分类引擎（仅标准库）。

旧仪器批次含未知项，每批枚举所有满足 fail_total 的可行补全（legacy.feasible_options）。
对现有候选范围（最多 3 项的频繁项集产生的全部正反向规则）与提交阈值，
在"所有可行补全"构成的空间上判定每条规则：

- certain  必然入选：每个可行全局补全下都满足支持度/置信度/提升度阈值且 lift>1
- possible 可能入选：至少一个补全入选、至少一个补全落选（各附逐批补全见证）
- impossible 不可能：所有补全均落选

全局补全 = 各批独立选择一份本地补全。以 (共同失败数 J, 前项批数 SA) 为单元做
Pareto 动态规划，单元内只保留后项批数 SB 的最小/最大可达值，精确刻画阈值判据的
上下界，并通过回溯指针还原逐批补全见证。中立批（各补全增量相同）计入确定性基线，
不进入 DP。每批本地补全至多 6 种，结果精确而非抽样近似。
"""
from itertools import combinations

from src.constants.assay import ITEMS, NAMES
from src.services.legacy import completion_to_row

MIN_SUPPORT_DEFAULT = 0.12
MIN_CONFIDENCE_DEFAULT = 0.65
MAX_ITEMSET_SIZE = 3


def _validate_params(params):
    try:
        min_support = float(params.get("min_support", MIN_SUPPORT_DEFAULT))
        min_confidence = float(params.get("min_confidence", MIN_CONFIDENCE_DEFAULT))
    except (ValueError, TypeError) as exc:
        raise ValueError("支持度与置信度须为有效比例。") from exc
    if not 0.05 <= min_support <= 0.5 or not 0.2 <= min_confidence <= 0.95:
        raise ValueError("最小支持度须0.05~0.5，最小置信度须0.2~0.95。")
    return min_support, min_confidence


def generate_candidate_rules():
    """现有候选范围：2~3 项频繁项集的全部非空真子集划分，正反向独立。"""
    rules = []
    for size in range(2, MAX_ITEMSET_SIZE + 1):
        for itemset in combinations(ITEMS, size):
            itemset_set = frozenset(itemset)
            for ante_size in range(1, size):
                for antecedent in combinations(sorted(itemset_set), ante_size):
                    a = frozenset(antecedent)
                    b = itemset_set - a
                    rules.append((a, b))
    return rules


def _label(itemset):
    return " + ".join(NAMES[k] for k in sorted(itemset))


def _batch_bitmap(row, assignment):
    values = dict(row["known"])
    values.update(assignment)
    return values


def _option_deltas(row, antecedent, consequent):
    """一批的每个可行补全对应增量 (dj, dsa, dsb)，按补全下标返回。"""
    deltas = []
    for assignment in row["options"]:
        values = _batch_bitmap(row, assignment)
        has_a = all(values[k] == 1 for k in antecedent)
        has_b = all(values[k] == 1 for k in consequent)
        deltas.append((1 if has_a and has_b else 0, 1 if has_a else 0, 1 if has_b else 0))
    return deltas


def _split_rows(rows, antecedent, consequent):
    """拆分中立批与分歧批。

    所有可行补全增量相同的批次对该规则是"中立"的，贡献确定性基线计数，
    不产生状态分支，无需进入 DP；只有增量随补全变化的分歧批进入前沿 DP。
    返回 (基线计数, 分歧批原始下标, 分歧批 [(row, deltas)])。
    """
    baseline = [0, 0, 0]
    active_indices = []
    active_pairs = []
    for row_index, row in enumerate(rows):
        deltas = _option_deltas(row, antecedent, consequent)
        if all(d == deltas[0] for d in deltas[1:]):
            dj, dsa, dsb = deltas[0]
            baseline[0] += dj
            baseline[1] += dsa
            baseline[2] += dsb
        else:
            active_indices.append(row_index)
            active_pairs.append((row, deltas))
    return baseline, active_indices, active_pairs


def frontier_layers(rows, antecedent, consequent):
    """分层二维单元 Pareto 动态规划（仅跑分歧批，中立批由调用方计入基线）。

    阈值判据对 J 单调增、对 SA/SB 单调减。状态以 (J, SA) 为单元：
    - 上前沿单元只保留可达的最小 SB（最可能通过阈值，决定"能否入选"）；
    - 下前沿单元只保留可达的最大 SB（最不可能通过，决定"是否全部入选"）。
    其余 SB 取值被同单元极值支配，剪枝安全；单元数 O(n²)，每批转移 O(n²·k)。
    每层保存 (父单元, 本批 option 下标) 回溯指针，用于还原逐批补全见证。
    返回 (upper_layers, lower_layers)，每层为 {(j, sa): (sb, parent, option_index)}。
    """
    upper_layers = [{(0, 0): (0, None, None)}]
    lower_layers = [{(0, 0): (0, None, None)}]
    for row, deltas in rows:
        up, low = {}, {}
        # 上前沿：同 (J, SA) 单元保留最小 SB
        for (j, sa), (sb, _, _) in upper_layers[-1].items():
            for option_index, (dj, dsa, dsb) in enumerate(deltas):
                cell = (j + dj, sa + dsa)
                new_sb = sb + dsb
                if cell not in up or new_sb < up[cell][0]:
                    up[cell] = (new_sb, (j, sa), option_index)
        # 下前沿：同 (J, SA) 单元保留最大 SB
        for (j, sa), (sb, _, _) in lower_layers[-1].items():
            for option_index, (dj, dsa, dsb) in enumerate(deltas):
                cell = (j + dj, sa + dsa)
                new_sb = sb + dsb
                if cell not in low or new_sb > low[cell][0]:
                    low[cell] = (new_sb, (j, sa), option_index)
        upper_layers.append(up)
        lower_layers.append(low)
    return upper_layers, lower_layers


def _reconstruct(layers, final_cell):
    """回溯分歧批的 option 路径，返回 {active_index: option_index}。"""
    choices = {}
    cell = final_cell
    for layer_index in range(len(layers) - 1, 0, -1):
        _, parent_cell, option_index = layers[layer_index][cell]
        choices[layer_index - 1] = option_index
        cell = parent_cell
    return choices


def _full_witness(rows, active_indices, choices):
    """把分歧批选择展开为覆盖全部批次的逐批补全（中立批取其唯一/等价补全）。"""
    option_by_row = {active_indices[k]: option for k, option in choices.items()}
    completions = []
    for row_index, row in enumerate(rows):
        option_index = option_by_row.get(row_index, 0)
        completions.append(completion_to_row(row, row["options"][option_index]))
    return completions


def _metrics(counts, total):
    j, sa, sb = counts
    support = j / total
    confidence = j / sa if sa else 0.0
    support_b = sb / total
    lift = confidence / support_b if support_b else 0.0
    return support, confidence, lift


def _passes(counts, total, min_support, min_confidence):
    j, sa, sb = counts
    if j == 0:
        return False
    support, confidence, lift = _metrics(counts, total)
    return support >= min_support and confidence >= min_confidence and lift > 1 + 1e-12


def _rule_key(antecedent, consequent):
    return "|".join(sorted(antecedent)) + "->" + "|".join(sorted(consequent))


def _rank_key(counts, total):
    """指标排序键：提升度、置信度、共同失败数。"""
    support, confidence, lift = _metrics(counts, total)
    return lift, confidence, counts[0]


def judge_rule(rows, antecedent, consequent, min_support, min_confidence):
    """判定单条规则，返回分类与逐批补全见证。"""
    total = len(rows)
    baseline, active_indices, active_pairs = _split_rows(rows, antecedent, consequent)
    upper_layers, lower_layers = frontier_layers(active_pairs, antecedent, consequent)
    upper = {(j + baseline[0], sa + baseline[1], sb + baseline[2])
             for (j, sa), (sb, _, _) in upper_layers[-1].items()}
    lower = {(j + baseline[0], sa + baseline[1], sb + baseline[2])
             for (j, sa), (sb, _, _) in lower_layers[-1].items()}
    # 上前沿最优点决定"是否存在入选补全"，下前沿最差点决定"是否全部入选"
    best = max(upper, key=lambda c: _rank_key(c, total))
    worst = min(lower, key=lambda c: _rank_key(c, total))
    best_cell = (best[0] - baseline[0], best[1] - baseline[1])
    worst_cell = (worst[0] - baseline[0], worst[1] - baseline[1])
    passes_any = _passes(best, total, min_support, min_confidence)
    passes_all = all(_passes(c, total, min_support, min_confidence) for c in lower)
    key = _rule_key(antecedent, consequent)
    base = {
        "rule_key": key,
        "antecedent": _label(antecedent),
        "consequent": _label(consequent),
        "antecedent_keys": sorted(antecedent),
        "consequent_keys": sorted(consequent),
    }
    if not passes_any:
        support, confidence, lift = _metrics(best, total)
        return {
            **base,
            "verdict": "impossible",
            "best_counts": {"joint": best[0], "antecedent": best[1], "consequent": best[2]},
            "best_support_pct": round(support * 100, 2),
            "best_confidence_pct": round(confidence * 100, 2),
            "best_lift": round(lift, 4),
        }
    if passes_all:
        support, confidence, lift = _metrics(worst, total)
        choices = _reconstruct(lower_layers, worst_cell)
        return {
            **base,
            "verdict": "certain",
            "worst_counts": {"joint": worst[0], "antecedent": worst[1], "consequent": worst[2]},
            "worst_support_pct": round(support * 100, 2),
            "worst_confidence_pct": round(confidence * 100, 2),
            "worst_lift": round(lift, 4),
            "certain_completion": _full_witness(rows, active_indices, choices),
        }
    # possible：各给一份入选与落选的逐批补全
    best_choices = _reconstruct(upper_layers, best_cell)
    worst_choices = _reconstruct(lower_layers, worst_cell)
    p_support, p_conf, p_lift = _metrics(best, total)
    f_support, f_conf, f_lift = _metrics(worst, total)
    return {
        **base,
        "verdict": "possible",
        "pass_witness": {
            "counts": {"joint": best[0], "antecedent": best[1], "consequent": best[2]},
            "support_pct": round(p_support * 100, 2),
            "confidence_pct": round(p_conf * 100, 2),
            "lift": round(p_lift, 4),
            "completions": _full_witness(rows, active_indices, best_choices),
        },
        "fail_witness": {
            "counts": {"joint": worst[0], "antecedent": worst[1], "consequent": worst[2]},
            "support_pct": round(f_support * 100, 2),
            "confidence_pct": round(f_conf * 100, 2),
            "lift": round(f_lift, 4),
            "completions": _full_witness(rows, active_indices, worst_choices),
        },
    }


def classify_rules(rows, params):
    """三分类核心（不校验批量），供分析入口与小规模对照测试复用。"""
    min_support, min_confidence = _validate_params(params)
    candidates = generate_candidate_rules()
    judgments = [
        judge_rule(rows, a, b, min_support, min_confidence)
        for a, b in candidates
    ]
    order = {"certain": 0, "possible": 1, "impossible": 2}
    judgments.sort(key=lambda j: (order[j["verdict"]], j["rule_key"]))
    for index, judgment in enumerate(judgments, 1):
        judgment["rule_id"] = f"U{index:02}"
    groups = {
        verdict: [j for j in judgments if j["verdict"] == verdict]
        for verdict in ("certain", "possible", "impossible")
    }
    return min_support, min_confidence, candidates, judgments, groups


def analyze_partial(rows, params):
    """对已通过 legacy 校验的批次执行三分类分析。rows 为 normalize_legacy_records 输出。"""
    if len(rows) < 30:
        raise ValueError("至少需要30批复检事务，避免极少样本误导规则。")
    min_support, min_confidence, candidates, judgments, groups = classify_rules(rows, params)
    completion_space = 1
    for row in rows:
        completion_space *= len(row["options"])
    uncertain_batches = sum(1 for row in rows if row["unknown_keys"])
    return {
        "kind": "partial",
        "summary": (
            f"{len(rows)} 批旧仪器记录中 {uncertain_batches} 批含未知项，"
            f"全局可行补全共 {completion_space} 种；{len(candidates)} 条候选规则里"
            f"必然入选 {len(groups['certain'])} 条、可能入选 {len(groups['possible'])} 条、"
            f"不可能入选 {len(groups['impossible'])} 条。"
        ),
        "metrics": [
            {"label": "旧仪器批次", "value": len(rows)},
            {"label": "含未知项批次", "value": uncertain_batches},
            {"label": "候选规则", "value": len(candidates)},
            {"label": "必然入选", "value": len(groups["certain"])},
            {"label": "可能入选", "value": len(groups["possible"])},
            {"label": "不可能入选", "value": len(groups["impossible"])},
        ],
        "thresholds": {"min_support": min_support, "min_confidence": min_confidence},
        "completion_space": completion_space,
        "judgments": judgments,
        "groups": groups,
        "findings": _build_findings(groups),
        "method": (
            "每批枚举满足失败总数的全部可行补全，全局补全空间上以动态规划精确判定；"
            "必然=全部补全均过阈值，可能=同时存在入选与落选补全（各附逐批补全见证），"
            "不可能=全部补全均落选。口径与完整数据一致：support=共同失败批/总批，"
            "confidence=support(A∪B)/support(A)，lift=confidence/support(B)。"
        ),
        "warnings": [
            "可能入选规则的结论依赖未知项补全，请展开逐批补全见证核对后再复核。",
            "共败关联不等于共同根因；旧仪器缺测会放大结论不确定性。",
        ],
    }


def _build_findings(groups):
    findings = []
    if groups["certain"]:
        findings.append(f"共有 {len(groups['certain'])} 条规则在任意可行补全下都入选，可优先复核。")
    if groups["possible"]:
        findings.append(
            f"{len(groups['possible'])} 条规则是否入选取决于缺失项如何补全，页面提供入选/落选两份逐批补全。"
        )
    if groups["impossible"]:
        findings.append(f"{len(groups['impossible'])} 条候选规则在任何补全下都无法过阈值，可排除。")
    findings.append("提升度大于1仅表示后项在前项出现时更常见，仍需对照仪器与制样记录独立复验。")
    return findings
