from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import READ_ONLY_DB_URL
from fastapi import HTTPException, status, Security
from fastapi.security import APIKeyHeader

engine_readonly = create_engine(READ_ONLY_DB_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)
SessionReadOnly = sessionmaker(bind=engine_readonly, autocommit=False, autoflush=False)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_readonly_db():
    db = SessionReadOnly()
    try:
        yield db
    finally:
        db.close()

async def verify_api_key(api_key: str = Security(api_key_header)):
    from config import API_READ_KEY
    if API_READ_KEY and api_key != API_READ_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid API key"}
        )
    return api_key
