from sqlalchemy import String, JSON, Double, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
    # full=完整五项 0/1；legacy=旧仪器仅 fail_total+部分单项
    kind: Mapped[str] = mapped_column(String(20), default='full')
    # 版本谱系：补录另存为新版本，指向被补录的原始批次
    version_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_note: Mapped[str] = mapped_column(String(200), default='')
