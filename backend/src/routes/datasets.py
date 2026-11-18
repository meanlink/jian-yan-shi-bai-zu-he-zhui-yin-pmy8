from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset
from src.schemas.dataset import DatasetInput, LegacyDatasetInput, DatasetVersionInput
from src.middlewares.auth import current_user, can_write
from src.services import datasets
from src.services.audit import record
from src.utils.serialization import dataset_dict
router = APIRouter(prefix='/datasets')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [dataset_dict(d) for d in db.scalars(select(Dataset).order_by(Dataset.id.desc()))]


@router.post('', status_code=201)
def create(data: DatasetInput, db=Depends(get_db), u=Depends(can_write)):
    d = datasets.create(db, data)
    record(db, u.email, 'dataset.create', {'id': d.id, 'rows': len(d.records), 'kind': d.kind})
    db.commit()
    return dataset_dict(d)


@router.post('/legacy', status_code=201)
def create_legacy(data: LegacyDatasetInput, db=Depends(get_db), u=Depends(can_write)):
    d, normalized = datasets.create_legacy(db, data)
    record(db, u.email, 'dataset.legacy_import',
           {'id': d.id, 'rows': len(normalized), 'rejected': 0})
    db.commit()
    return dataset_dict(d)


@router.post('/{id}/versions', status_code=201)
def create_version(id: int, data: DatasetVersionInput, db=Depends(get_db), u=Depends(can_write)):
    d = datasets.create_version(db, id, data)
    record(db, u.email, 'dataset.version_create',
           {'id': d.id, 'parent_id': id, 'rows': len(d.records)})
    db.commit()
    return dataset_dict(d)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    return {**dataset_dict(d), 'records': d.records}
