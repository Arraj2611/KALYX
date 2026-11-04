import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.control.models  # noqa: F401
import app.data.models  # noqa: F401
from app.data.database import Base


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
