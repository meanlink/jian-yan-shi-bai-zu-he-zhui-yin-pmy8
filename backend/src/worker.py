import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, RuleJudgment
from src.services.business import analyze
from src.services import jobs as job_service
from src.services.reports import deliver
from src.services.audit import record
logging.basicConfig(level=logging.INFO)


def execute(job_id):
    with Session() as db:
        j = db.get(Job, job_id)
        if not j or j.status != 'queued':
            return
        j.status = 'running'
        db.commit()
        try:
            if getattr(j, 'analysis_kind', 'full') == 'legacy':
                _execute_partial(db, j)
            else:
                d = db.get(Dataset, j.dataset_id)
                result = analyze(d.records, j.params)
                json.dumps(result, allow_nan=False)
                j.result = result
                j.status = 'completed'
                j.finished_at = time.time()
                record(db, 'worker', 'job.completed', {'id': j.id})
            db.commit()
        except Exception as e:
            logging.exception('Analysis failed')
            db.rollback()
            j = db.get(Job, job_id)
            j.status = 'failed'
            j.error = str(e)[:990]
            j.finished_at = time.time()
            record(db, 'worker', 'job.failed', {'id': j.id, 'error': j.error})
            db.commit()


def _execute_partial(db, job):
    """部分数据任务：从已判完的规则续跑，判定齐全才显示完成。"""
    finished = job_service.run_partial(db, job)
    if not finished:
        # 理论上单轮即可跑完；未齐全时保持 running，等待下一轮续跑
        return
    judgments = list(db.scalars(
        select(RuleJudgment).where(RuleJudgment.job_id == job.id)
    ))
    result = job_service.assemble_partial_result(job, judgments)
    json.dumps(result, allow_nan=False)
    job.result = result
    job.status = 'completed'
    job.finished_at = time.time()
    record(db, 'worker', 'job.completed', {'id': job.id, 'rules': len(judgments)})


def tick():
    with Session() as db:
        queued = list(db.scalars(select(Job.id).where(Job.status == 'queued').limit(3)))
    for job_id in queued:
        execute(job_id)
    # 续跑兜底：running 的部分数据任务若仍有未判规则，从断点继续（重试不重复登记）
    with Session() as db:
        running = list(db.scalars(select(Job).where(Job.status == 'running')))
        for job in running:
            if getattr(job, 'analysis_kind', 'full') != 'legacy':
                continue
            registered = db.scalars(
                select(RuleJudgment.id).where(RuleJudgment.job_id == job.id).limit(1)
            ).first()
            if registered is None:
                continue  # 尚无登记，交给正常 execute 首轮驱动
            try:
                _execute_partial(db, job)
                db.commit()
            except Exception:
                logging.exception('Partial job resume failed')
                db.rollback()
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled == True, Report.next_run <= time.time())):
            d = deliver(db, r)
            if d:
                record(db, 'worker', 'report.delivered', {'id': r.id, 'delivery': d.id})
        db.commit()


def main():
    r = Redis.from_url(REDIS_URL, socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status == 'running')):
            # 部分数据任务保留 running 以便续跑；仅把无任何判定登记的任务重新排队
            has_progress = db.scalar(
                select(RuleJudgment.id).where(RuleJudgment.job_id == j.id).limit(1)
            )
            if getattr(j, 'analysis_kind', 'full') == 'legacy' and has_progress is not None:
                record(db, 'worker', 'job.resume', {'id': j.id})
                continue
            j.status = 'queued'
            record(db, 'worker', 'job.recovered', {'id': j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item = r.blpop('analysis:queue', timeout=1)
            if item:
                execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry')
            time.sleep(2)


if __name__ == '__main__':
    main()
