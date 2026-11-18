"""部分数据任务的逐规则判定循环（不依赖 ORM，便于离线测试与中断续跑）。"""
from src.services import legacy, uncertain


def pending_sequences(candidate_count, done_keys, rule_keys):
    """给定候选总数、已判 rule_key 集合与候选键序列，返回待判下标。"""
    done = set(done_keys)
    return [i for i, key in enumerate(rule_keys) if key not in done]


def run_partial_engine(records, params, done_keys, sink):
    """判定所有尚未登记的规则，每条结果交由 sink(sequence, rule_key, judgment) 持久化。

    - records: 提交时快照中的旧仪器原始记录
    - done_keys: 已判完规则的 rule_key（中断恢复点）
    - sink: 单条持久化回调，须自行保证提交与唯一约束幂等
    返回 (rule_keys, newly_judged_count)。判定齐全的判断由调用方比对总数。
    """
    rows = legacy.normalize_legacy_records(records)
    min_support, min_confidence = uncertain._validate_params(params)
    candidates = uncertain.generate_candidate_rules()
    rule_keys = [uncertain._rule_key(a, b) for a, b in candidates]
    done = set(done_keys)
    newly = 0
    for sequence, (antecedent, consequent) in enumerate(candidates):
        rule_key = rule_keys[sequence]
        if rule_key in done:
            continue
        judgment = uncertain.judge_rule(rows, antecedent, consequent, min_support, min_confidence)
        sink(sequence, rule_key, judgment)
        done.add(rule_key)
        newly += 1
    return rule_keys, newly
