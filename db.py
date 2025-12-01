# db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 기본 DB → SQLite 사용
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./dongne_saenghwal.db"   # 기본 SQLite 파일
)

# SQLite 전용 옵션 (Thread 문제 방지)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
