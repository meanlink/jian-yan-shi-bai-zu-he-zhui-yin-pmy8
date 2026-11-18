from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # 旧仪器部分数据任务：分析沿用提交时的数据版本快照
    analysis_kind: Mapped[str] = mapped_column(String(20), default='full')
    input_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    input_checksum: Mapped[str] = mapped_column(String(64), default='')
    total_rules: Mapped[int] = mapped_column(Integer, default=0)


class RuleJudgment(Base):
    """部分数据任务的逐规则判定登记。唯一约束保证重试不重复登记。"""
    __tablename__ = 'rule_judgments'
    __table_args__ = (UniqueConstraint('job_id', 'rule_key', name='uq_judgment_job_rule'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id', ondelete='CASCADE'), index=True)
    rule_key: Mapped[str] = mapped_column(String(120))
    verdict: Mapped[str] = mapped_column(String(20))
    sequence: Mapped[int] = mapped_column(Integer)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Double)
