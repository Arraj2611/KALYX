"""
Database connection and session management.
"""
import logging
from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from contextlib import contextmanager

from app.config import settings

logger = logging.getLogger(__name__)

# Create engine
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ECHO,
    pool_pre_ping=True,
    poolclass=NullPool if settings.DATABASE_ECHO else None,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Metadata
metadata = MetaData()


async def init_db():
    """Initialize database connection and create tables."""
    try:
        # Import all models to ensure they're registered
        from app.data import models  # noqa
        from app.control import models as control_models  # noqa
        
        # Create tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        raise


async def close_db():
    """Close database connections."""
    try:
        engine.dispose()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error closing database: {e}", exc_info=True)


@contextmanager
def get_db():
    """Get database session context manager."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """Get database session (for dependency injection)."""
    db = SessionLocal()
    try:
        return db
    except Exception as e:
        logger.error(f"Error creating database session: {e}", exc_info=True)
        raise

