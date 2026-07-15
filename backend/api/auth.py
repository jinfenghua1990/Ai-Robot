from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import READ_ONLY_DB_URL
from fastapi import HTTPException, Query, status, Security
from fastapi.security import APIKeyHeader
from typing import Optional

engine_readonly = create_engine(READ_ONLY_DB_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)
SessionReadOnly = sessionmaker(bind=engine_readonly, autocommit=False, autoflush=False)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_readonly_db():
    db = SessionReadOnly()
    try:
        yield db
    finally:
        db.close()

async def verify_api_key(
    api_key_header_val: Optional[str] = Security(api_key_header),
    api_key_query: Optional[str] = Query(None, alias="api_key", include_in_schema=False),
):
    """验证 API Key（Header X-API-Key 或 query param api_key 二选一）。
    当环境变量 API_READ_KEY 未配置时，允许所有请求通过（开发模式）。"""
    from config import API_READ_KEY
    api_key = api_key_header_val or api_key_query
    if API_READ_KEY and api_key != API_READ_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid API key"}
        )
    return api_key
