import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit
from src.services.business import metadata, seed_records, analyze
from src.services import legacy
from src.services.reports import deliver
from src.utils.security import hash_password
from src.utils.serialization import checksum


def _legacy_demo_records(full_rows):
    """从完整模拟数据退化出旧仪器格式：保留 fail_total，仅暴露部分单项，其余置空。"""
    partial = []
    for index, row in enumerate(full_rows):
        item_keys = [k for k in row if k != 'batch_id']
        total = sum(int(row[k]) for k in item_keys)
        kept = item_keys[: 1 + index % 3]  # 每批仅保留 1~3 个已知单项
        partial.append({
            'batch_id': row['batch_id'],
            'fail_total': total,
            **{k: (row[k] if k in kept else None) for k in item_keys},
        })
    return partial


def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        # 旧仪器部分项演示批次：同一观测退化而来，缺失项留空
        legacy_name='旧仪器归档 · 失败总数与部分单项'
        legacy_dataset=db.scalar(select(Dataset).where(Dataset.name==legacy_name))
        if not legacy_dataset:
            raw_partial=_legacy_demo_records(seed_records())
            normalized=legacy.normalize_legacy_records(raw_partial)
            stored=[legacy.partial_view(r) for r in normalized]
            legacy_dataset=Dataset(name=legacy_name,source='legacy-assay-202610.csv',records=stored,
                                   checksum=checksum(stored),created_at=time.time(),kind='legacy',
                                   version_note='旧仪器仅存每批失败总数与部分单项')
            db.add(legacy_dataset); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
