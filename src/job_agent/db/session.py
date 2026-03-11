"""Database engine and session factory."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from job_agent.config import Settings
from job_agent.db.models import Base

_engine = None
_session_factory: sessionmaker[Session] | None = None


def get_engine(settings: Settings | None = None):
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        if settings is None:
            from job_agent.config import load_settings

            settings = load_settings()
        _engine = create_engine(
            settings.db_path,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    """Get or create the session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine(settings)
        _session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return _session_factory


def get_session(settings: Settings | None = None) -> Session:
    """Create a new database session."""
    factory = get_session_factory(settings)
    return factory()


def init_db(settings: Settings | None = None) -> None:
    """Create all database tables and migrate missing columns."""
    engine = get_engine(settings)
    Base.metadata.create_all(engine)
    _migrate(engine)


def _migrate(engine) -> None:
    """Add columns that may be missing from an older schema."""
    import sqlalchemy

    migrations = [
        ("jobs", "bookmarked", "BOOLEAN DEFAULT 0"),
        ("jobs", "duplicate_of_id", "INTEGER REFERENCES jobs(id)"),
    ]

    with engine.connect() as conn:
        for table, column, col_def in migrations:
            try:
                conn.execute(
                    sqlalchemy.text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
                    )
                )
                conn.commit()
            except sqlalchemy.exc.OperationalError:
                # Column already exists
                conn.rollback()


def reset_engine() -> None:
    """Reset the engine and session factory (for testing)."""
    global _engine, _session_factory
    if _engine:
        _engine.dispose()
    _engine = None
    _session_factory = None
