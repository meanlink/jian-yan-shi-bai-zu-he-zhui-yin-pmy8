from sqlalchemy import text
from src.config.database import Base, engine
from src import models


def _has_column(inspector, table, column):
    return any(c['name'] == column for c in inspector.get_columns(table))


def migrate():
    Base.metadata.create_all(engine)
    # 对已存在的旧库补列（create_all 不会修改既有表结构）
    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with engine.begin() as conn:
        if 'datasets' in existing:
            if not _has_column(inspector, 'datasets', 'kind'):
                conn.execute(text("ALTER TABLE datasets ADD COLUMN kind VARCHAR(20) DEFAULT 'full'"))
            if not _has_column(inspector, 'datasets', 'version_of_id'):
                conn.execute(text("ALTER TABLE datasets ADD COLUMN version_of_id INTEGER NULL"))
            if not _has_column(inspector, 'datasets', 'version_note'):
                conn.execute(text("ALTER TABLE datasets ADD COLUMN version_note VARCHAR(200) DEFAULT ''"))
        if 'jobs' in existing:
            if not _has_column(inspector, 'jobs', 'analysis_kind'):
                conn.execute(text("ALTER TABLE jobs ADD COLUMN analysis_kind VARCHAR(20) DEFAULT 'full'"))
            if not _has_column(inspector, 'jobs', 'input_snapshot'):
                conn.execute(text("ALTER TABLE jobs ADD COLUMN input_snapshot JSON"))
            if not _has_column(inspector, 'jobs', 'input_checksum'):
                conn.execute(text("ALTER TABLE jobs ADD COLUMN input_checksum VARCHAR(64) DEFAULT ''"))
            if not _has_column(inspector, 'jobs', 'total_rules'):
                conn.execute(text("ALTER TABLE jobs ADD COLUMN total_rules INTEGER DEFAULT 0"))


if __name__ == '__main__':
    migrate()
