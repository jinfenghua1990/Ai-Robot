"""共享 pytest fixtures"""
import os
import sys
import pytest

# 确保后端目录在 path 中
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
sys.path.insert(0, backend_dir)


@pytest.fixture
def db_session():
    """提供隔离的 DB session，测试结束后回滚"""
    from db.connection import SessionLocal
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()
