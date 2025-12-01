# models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime
from db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    email = Column(String, unique=True, nullable=True)      # 이메일 (카카오/일반 공통)
    username = Column(String, unique=True, nullable=False)  # 로그인용 아이디 or kakao_xxx
    password_hash = Column(String, nullable=True)           # 일반 로그인용 비번 해시 (카카오는 빈값 가능)
    login_type = Column(String, nullable=False)             # "email" / "kakao"

    kakao_id = Column(String, unique=True, nullable=True)   # 카카오 고유 ID

    is_admin = Column(Boolean, default=False)               # 운영자 여부
    is_active = Column(Boolean, default=True)               # 차단/탈퇴 처리

    created_at = Column(DateTime, default=datetime.utcnow)  # 가입일
    last_login = Column(DateTime, default=datetime.utcnow)  # 최근 로그인

class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)                # 업체 이름
    category = Column(String, nullable=False)            # 카테고리(에어컨, 세탁기 등)
    region = Column(String, nullable=False)              # 지역(구/시 단위)
    price_min = Column(Float, nullable=True)             # 최저 가격
    price_max = Column(Float, nullable=True)             # 최고 가격
    description = Column(String, nullable=True)          # 간단 설명
    phone = Column(String, nullable=True)                # 연락처
    address = Column(String, nullable=True)              # 주소
    is_premium = Column(Boolean, default=False)          # 상단 노출 여부
