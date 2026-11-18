from pydantic import BaseModel, Field


class DatasetInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=5, max_length=5000)


class LegacyDatasetInput(DatasetInput):
    """旧仪器导入：fail_total + 部分单项，未知项留空或 null。"""
    version_note: str = Field(default='', max_length=200)


class DatasetVersionInput(BaseModel):
    """基于已有批次补录后另存的新版本（完整五项数据）。"""
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=5, max_length=5000)
    version_note: str = Field(default='', max_length=200)
