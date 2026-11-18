import math
import time

from fastapi import HTTPException
from sqlalchemy import select

from src.models import Dataset
from src.services.business import metadata
from src.services import legacy
from src.utils.serialization import checksum


def _ensure_unique_name(db, name):
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')


def _validate_full_records(records):
    """完整五项 0/1 数据的既有校验口径。"""
    columns = metadata()['columns']
    for index, row in enumerate(records):
        for c in columns:
            value = row.get(c['key'])
            if value is None or value == '':
                raise HTTPException(422, f'第 {index + 1} 行缺少字段 {c["label"]}')
            if c['type'] == 'number':
                try:
                    if isinstance(value, bool) or not math.isfinite(float(value)):
                        raise ValueError()
                    row[c['key']] = float(value)
                except (TypeError, ValueError, OverflowError):
                    raise HTTPException(422, f'第 {index + 1} 行 {c["label"]} 必须为有限数值')


def create(db, data):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    _ensure_unique_name(db, name)
    _validate_full_records(data.records)
    d = Dataset(name=name, source=data.source, records=data.records,
                checksum=checksum(data.records), created_at=time.time(), kind='full')
    db.add(d)
    db.flush()
    return d


def create_legacy(db, data):
    """旧仪器导入：逐批校验 fail_total 与已知项是否可行，任一不可行整批拒收。"""
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    _ensure_unique_name(db, name)
    try:
        normalized = legacy.normalize_legacy_records(data.records)
    except ValueError as exc:
        raise HTTPException(422, f'旧仪器数据拒收：{exc}') from exc
    stored = [legacy.partial_view(row) for row in normalized]
    d = Dataset(name=name, source=data.source, records=stored,
                checksum=checksum(stored), created_at=time.time(), kind='legacy',
                version_note=getattr(data, 'version_note', '') or '旧仪器失败总数+部分单项导入')
    db.add(d)
    db.flush()
    return d, normalized


def create_version(db, parent_id, data):
    """补录批次另存为新版本：不改写原批次，保留版本谱系。"""
    parent = db.get(Dataset, parent_id)
    if not parent:
        raise HTTPException(404, '原始数据批次不存在')
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    _ensure_unique_name(db, name)
    _validate_full_records(data.records)
    d = Dataset(name=name, source=data.source, records=data.records,
                checksum=checksum(data.records), created_at=time.time(), kind='full',
                version_of_id=parent.id,
                version_note=data.version_note or f'补录自 {parent.name}')
    db.add(d)
    db.flush()
    return d
