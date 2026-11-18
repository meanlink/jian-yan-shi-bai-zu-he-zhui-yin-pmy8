import time

from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, RuleJudgment
from src.services.business import metadata
from src.services import legacy, uncertain
from src.services.partial_runner import run_partial_engine
from src.utils.serialization import checksum


def create(db, data, user):
    dataset = db.get(Dataset, data.dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    allowed = {p['key']: p for p in metadata().get('parameters', [])}
    if set(data.params) - set(allowed):
        raise HTTPException(422, '包含未知分析参数')
    params = {k: p['default'] for k, p in allowed.items()}
    params.update(data.params)
    for key, p in allowed.items():
        v = params[key]
        if p['type'] == 'number':
            try:
                v = float(v)
                if not (p.get('min', -1e9) <= v <= p.get('max', 1e9)):
                    raise ValueError()
                params[key] = v
            except (ValueError, TypeError):
                raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options', [])]:
            raise HTTPException(422, f'{p["label"]} 不是有效选项')

    # 分析沿用提交时的数据版本：快照与指纹随任务保存，后续补录不影响本任务
    kind = getattr(dataset, 'kind', 'full')
    if kind == 'legacy':
        normalized = legacy.normalize_legacy_records(dataset.records)
        if len(normalized) < 30:
            raise HTTPException(422, '至少需要30批复检事务，避免极少样本误导规则。')
        total_rules = len(uncertain.generate_candidate_rules())
    else:
        normalized = None
        total_rules = 0

    job = Job(
        name=data.name, dataset_id=dataset.id, params=params,
        created_by=user.id, created_at=time.time(), status='queued',
        analysis_kind=kind,
        input_snapshot={'records': dataset.records} if kind == 'legacy' else {},
        input_checksum=checksum(dataset.records),
        total_rules=total_rules,
    )
    db.add(job)
    db.flush()
    return job


def enqueue(job_id):
    try:
        r = Redis.from_url(REDIS_URL)
        r.rpush('analysis:queue', job_id)
        r.close()
    except Exception:
        pass  # SQL queued status is the durable fallback


def run_partial(db, job):
    """部分数据任务的可续跑执行：逐规则判定并幂等登记，全部判完才汇总完成。

    返回 True 表示本批次已判完全部规则；False 表示仍有规则未判。
    """
    records = (job.input_snapshot or {}).get('records', [])
    existing = set(db.scalars(
        select(RuleJudgment.rule_key).where(RuleJudgment.job_id == job.id)
    ).all())

    def sink(sequence, rule_key, judgment):
        try:
            db.add(RuleJudgment(
                job_id=job.id, rule_key=rule_key, verdict=judgment['verdict'],
                sequence=sequence, detail=judgment, created_at=time.time(),
            ))
            # 每条规则独立提交：中断后已提交的判定不丢，重跑从下一条续
            db.commit()
        except IntegrityError:
            # 唯一约束 (job_id, rule_key) 兜底：并发/重试不重复登记
            db.rollback()

    rule_keys, _ = run_partial_engine(records, job.params, existing, sink)
    judged = db.scalar(
        select(RuleJudgment.rule_key).where(RuleJudgment.job_id == job.id).limit(1)
    )
    total_judged = len(set(db.scalars(
        select(RuleJudgment.rule_key).where(RuleJudgment.job_id == job.id)
    ).all()))
    return total_judged >= len(rule_keys) and judged is not None


def assemble_partial_result(job, judgments):
    """按候选顺序汇总全部持久化判定，生成部分数据任务结果（不重复计算）。"""
    ordered = sorted(judgments, key=lambda x: x.sequence)
    rows = legacy.normalize_legacy_records((job.input_snapshot or {}).get('records', []))
    completion_space = 1
    for row in rows:
        completion_space *= len(row['options'])
    uncertain_batches = sum(1 for row in rows if row['unknown_keys'])
    details = [j.detail for j in ordered]
    groups = {
        verdict: [j.detail for j in ordered if j.verdict == verdict]
        for verdict in ('certain', 'possible', 'impossible')
    }
    min_support, min_confidence = uncertain._validate_params(job.params)
    return {
        'kind': 'partial',
        'summary': (
            f"{len(rows)} 批旧仪器记录中 {uncertain_batches} 批含未知项，"
            f"全局可行补全共 {completion_space} 种；{len(ordered)} 条候选规则里"
            f"必然入选 {len(groups['certain'])} 条、可能入选 {len(groups['possible'])} 条、"
            f"不可能入选 {len(groups['impossible'])} 条。"
        ),
        'metrics': [
            {'label': '旧仪器批次', 'value': len(rows)},
            {'label': '含未知项批次', 'value': uncertain_batches},
            {'label': '候选规则', 'value': len(ordered)},
            {'label': '必然入选', 'value': len(groups['certain'])},
            {'label': '可能入选', 'value': len(groups['possible'])},
            {'label': '不可能入选', 'value': len(groups['impossible'])},
        ],
        'thresholds': {'min_support': min_support, 'min_confidence': min_confidence},
        'completion_space': completion_space,
        'judgments': details,
        'groups': groups,
        'findings': uncertain._build_findings(groups),
        'method': (
            '每批枚举满足失败总数的全部可行补全，全局补全空间上以 Pareto 动态规划精确判定；'
            '必然=全部补全均过阈值，可能=同时存在入选与落选补全（各附逐批补全见证），'
            '不可能=全部补全均落选。口径与完整数据一致：support=共同失败批/总批，'
            'confidence=support(A∪B)/support(A)，lift=confidence/support(B)。'
        ),
        'warnings': [
            '可能入选规则的结论依赖未知项补全，请展开逐批补全见证核对后再复核。',
            '共败关联不等于共同根因；旧仪器缺测会放大结论不确定性。',
        ],
        'judged_rules': len(ordered),
        'total_rules': job.total_rules,
    }
