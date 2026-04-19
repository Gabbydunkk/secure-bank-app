# app/models/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# 1. Environment Variable Usage: No hardcoded passwords!
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

# 2. Connection Pooling & Security Configuration
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    
    # SECURE PROGRAMMING STANDARDS:
    # pool_size: Limit concurrent connections to prevent DoS (Denial of Service)
    # max_overflow: Allow temporary spikes in traffic
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    
    # SSL: default "require" – no silent downgrade to plaintext. For local dev without SSL, set DATABASE_SSLMODE=prefer in .env.
    connect_args={"sslmode": settings.DATABASE_SSLMODE}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()