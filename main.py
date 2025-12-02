# ================================================================
#   동네링크(DongneLink) — MAIN.PY (회원 DB + 동네생활 글쓰기/이미지)
# ================================================================

import hashlib
import json
import os
import uuid
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Optional

from fastapi import (
    FastAPI, Request, Form, Depends, HTTPException,
    UploadFile, File
)
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import httpx

from sqlalchemy.orm import Session

from db import SessionLocal, engine, Base
from models import User, Provider

# 🔥 DB 테이블 생성
Base.metadata.create_all(bind=engine)

# ------------------------------------------------------------
# 경로 설정
# ------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

# 업로드 경로
UPLOAD_DIR = STATIC_DIR / "uploads"
LIFESTYLE_UPLOAD_DIR = STATIC_DIR / "lifestyle"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LIFESTYLE_UPLOAD_DIR, exist_ok=True)

# ------------------------------------------------------------
# FastAPI 설정
# ------------------------------------------------------------
app = FastAPI()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ------------------------------------------------------------
# 🔐 카카오 REST API 키 (client_id)
# ------------------------------------------------------------
KAKAO_CLIENT_ID = os.getenv("KAKAO_CLIENT_ID")
redirect_uri = "https://dongnelink.onrender.com/auth/kakao/callback"
print(">>> KAKAO_CLIENT_ID:", KAKAO_CLIENT_ID)

# ------------------------------------------------------------
# 관리자 계정 (최초 1개는 코드로 관리)
# ------------------------------------------------------------
ADMIN_USERNAME = "taehwan4381@daum.net"
ADMIN_PASSWORD = "taehwan4381@"  

# ------------------------------------------------------------
# In-memory DB
# ------------------------------------------------------------
USERS_LEGACY: list[dict] = []
BUSINESSES: list[dict] = []
REVIEWS: list[dict] = []
NEWS_POSTS: list[dict] = []

_business_id_seq = 1

# ------------------------------------------------------------
# Util
# ------------------------------------------------------------
def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request) -> Optional[str]:
    return request.cookies.get("user")


def is_admin(request: Request) -> bool:
    return request.cookies.get("is_admin") == "1"


def admin_required(request: Request) -> str:
    if not is_admin(request):
        raise HTTPException(403, "관리자 전용 기능입니다.")
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def get_user_by_kakao_id(db: Session, kakao_id: str) -> Optional[User]:
    return db.query(User).filter(User.kakao_id == str(kakao_id)).first()


# =============================================================
#   행정동 JSON
# =============================================================
with open(DATA_DIR / "locations_capital.json", encoding="utf-8") as f:
    raw_locations = json.load(f)

location_tree: dict = defaultdict(lambda: defaultdict(list))

for r in raw_locations:
    location_tree[r["sido"]][r["sigungu"]].append(r["dong"])

for s in location_tree:
    for g in location_tree[s]:
        location_tree[s][g].sort()

CAPITAL_SIDO = ["서울특별시", "인천광역시", "경기도"]


def validate_location(sido: str, sigungu: str, dong: str):
    if sido not in location_tree:
        raise HTTPException(400, "잘못된 시/도")
    if sigungu not in location_tree[sido]:
        raise HTTPException(400, "잘못된 시/군/구")
    if dong not in location_tree[sido][sigungu]:
        raise HTTPException(400, "잘못된 동")


# =============================================================
# API - 행정동
# =============================================================
@app.get("/api/locations/sido")
def api_sido():
    return CAPITAL_SIDO


@app.get("/api/locations/sigungu")
def api_sigungu(sido: str):
    return sorted(location_tree[sido].keys())


@app.get("/api/locations/dong")
def api_dong(sido: str, sigungu: str):
    return location_tree[sido][sigungu]


# =============================================================
# 홈 (동네링크 메인)
# =============================================================
CATEGORY_META = {
    "lifestyle": {"name": "동네생활"},
    "food": {"name": "동네맛집"},
    "repair": {"name": "가전수리"},
}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "user": user,
            "categories": CATEGORY_META,
        },
    )
# =============================================================
# 동 선택 페이지
# =============================================================
@app.get("/select-location", response_class=HTMLResponse)
def select_location(
    request: Request,
    category: str,
    user=Depends(get_current_user),
):
    if category not in CATEGORY_META:
        raise HTTPException(404, "잘못된 카테고리입니다.")

    return templates.TemplateResponse(
        "select_location.html",
        {
            "request": request,
            "user": user,
            "category": category,
            "category_name": CATEGORY_META[category]["name"],
            "sido_list": CAPITAL_SIDO,
        },
    )


# =============================================================
# 동네생활 페이지 (글 목록)
# =============================================================
@app.get("/lifestyle", response_class=HTMLResponse)
def lifestyle_page(
    request: Request,
    sido: str,
    sigungu: str,
    dong: str,
    user=Depends(get_current_user),
):
    validate_location(sido, sigungu, dong)

    posts = [
        p
        for p in NEWS_POSTS
        if p["sido"] == sido and p["sigungu"] == sigungu and p["dong"] == dong
    ]

    return templates.TemplateResponse(
        "lifestyle.html",
        {
            "request": request,
            "user": user,
            "sido": sido,
            "sigungu": sigungu,
            "dong": dong,
            "news_posts": posts,
        },
    )


# 🔥 동네생활 글쓰기 (GET)
@app.get("/lifestyle/new", response_class=HTMLResponse)
def lifestyle_new_page(
    request: Request,
    sido: str,
    sigungu: str,
    dong: str,
    user=Depends(get_current_user),
):
    if not user:
        return RedirectResponse("/auth/login", 302)

    return templates.TemplateResponse(
        "lifestyle_form.html",
        {
            "request": request,
            "user": user,
            "sido": sido,
            "sigungu": sigungu,
            "dong": dong,
        },
    )


# 🔥 동네생활 글쓰기 (POST + 이미지)
@app.post("/lifestyle/new")
def lifestyle_new(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    sido: str = Form(...),
    sigungu: str = Form(...),
    dong: str = Form(...),
    image: UploadFile = File(None),
    user=Depends(get_current_user),
):
    if not user:
        return RedirectResponse("/auth/login", 302)

    validate_location(sido, sigungu, dong)

    image_url = None
    if image:
        ext = image.filename.split(".")[-1] if "." in image.filename else "jpg"
        filename = f"{uuid.uuid4()}.{ext}"
        save_path = LIFESTYLE_UPLOAD_DIR / filename
        with open(save_path, "wb") as f:
            shutil.copyfileobj(image.file, f)
        image_url = f"/static/lifestyle/{filename}"

    NEWS_POSTS.append(
        {
            "id": len(NEWS_POSTS) + 1,
            "title": title,
            "content": content,
            "user": user,
            "sido": sido,
            "sigungu": sigungu,
            "dong": dong,
            "image_url": image_url,
        }
    )

    return RedirectResponse(
        f"/lifestyle?sido={sido}&sigungu={sigungu}&dong={dong}",
        status_code=302,
    )


# =============================================================
# 업소 헬퍼
# =============================================================
def ensure_business_defaults(b: dict):
    b.setdefault("phone", None)
    b.setdefault("homepage", None)
    b.setdefault("blog", None)
    b.setdefault("instagram", None)
    b.setdefault("address_road", None)
    b.setdefault("address_detail", None)
    b.setdefault("lat", None)
    b.setdefault("lng", None)
    b.setdefault("hours_mon", None)
    b.setdefault("hours_tue", None)
    b.setdefault("hours_wed", None)
    b.setdefault("hours_thu", None)
    b.setdefault("hours_fri", None)
    b.setdefault("hours_sat", None)
    b.setdefault("hours_sun", None)
    b.setdefault("off_day", None)
    b.setdefault("opt_delivery", False)
    b.setdefault("opt_reservation", False)
    b.setdefault("opt_parking", False)
    b.setdefault("opt_pet", False)
    b.setdefault("opt_wifi", False)
    b.setdefault("opt_group", False)
    b.setdefault("menus", [])
    b.setdefault("services", [])


def get_business(bid: int):
    b = next((x for x in BUSINESSES if x["id"] == bid), None)
    if b:
        ensure_business_defaults(b)
    return b


def get_reviews(bid: int):
    return [r for r in REVIEWS if r["business_id"] == bid]


def get_filtered_businesses(kind, sido, sigungu, dong, category=None):
    items = [b for b in BUSINESSES if b["kind"] == kind and b.get("approved")]

    items = [
        b
        for b in items
        if b["sido"] == sido and b["sigungu"] == sigungu and b["dong"] == dong
    ]

    if category:
        items = [b for b in items if b["category"] == category]

    return items


# =============================================================
# 리스트 페이지 (맛집/수리)
# =============================================================
@app.get("/food", response_class=HTMLResponse)
def food_list(
    request: Request,
    sido: str,
    sigungu: str,
    dong: str,
    category: str = None,
    user=Depends(get_current_user),
):
    validate_location(sido, sigungu, dong)
    items = get_filtered_businesses("food", sido, sigungu, dong, category)
    categories = sorted({b["category"] for b in BUSINESSES if b["kind"] == "food"})

    return templates.TemplateResponse(
        "food_list.html",
        {
            "request": request,
            "user": user,
            "items": items,
            "categories": categories,
            "sido": sido,
            "sigungu": sigungu,
            "dong": dong,
        },
    )


@app.get("/repair", response_class=HTMLResponse)
def repair_list(
    request: Request,
    sido: str,
    sigungu: str,
    dong: str,
    category: str = None,
    user=Depends(get_current_user),
):
    validate_location(sido, sigungu, dong)
    items = get_filtered_businesses("repair", sido, sigungu, dong, category)
    categories = sorted({b["category"] for b in BUSINESSES if b["kind"] == "repair"})

    return templates.TemplateResponse(
        "repair_list.html",
        {
            "request": request,
            "user": user,
            "items": items,
            "categories": categories,
            "sido": sido,
            "sigungu": sigungu,
            "dong": dong,
        },
    )


# =============================================================
# BUSINESS 등록
# =============================================================
@app.get("/business/register", response_class=HTMLResponse)
def business_register_page(request: Request, user=Depends(get_current_user)):
    if not user:
        return RedirectResponse("/auth/login", 302)

    return templates.TemplateResponse(
        "business_form.html",
        {"request": request, "user": user, "sido_list": CAPITAL_SIDO},
    )
@app.post("/business/new")
def business_new(
    request: Request,
    kind: str = Form(...),
    sido: str = Form(...),
    sigungu: str = Form(...),
    dong: str = Form(...),
    category: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    phone: str = Form(None),
    homepage: str = Form(None),
    blog: str = Form(None),
    instagram: str = Form(None),
    address_road: str = Form(None),
    address_detail: str = Form(None),
    lat: str = Form(None),
    lng: str = Form(None),
    hours_mon: str = Form(None),
    hours_tue: str = Form(None),
    hours_wed: str = Form(None),
    hours_thu: str = Form(None),
    hours_fri: str = Form(None),
    hours_sat: str = Form(None),
    hours_sun: str = Form(None),
    off_day: str = Form(None),
    opt_delivery: str = Form(None),
    opt_reservation: str = Form(None),
    opt_parking: str = Form(None),
    opt_pet: str = Form(None),
    opt_wifi: str = Form(None),
    opt_group: str = Form(None),
    menu_name1: str = Form(None),
    menu_price1: str = Form(None),
    menu_name2: str = Form(None),
    menu_price2: str = Form(None),
    menu_name3: str = Form(None),
    menu_price3: str = Form(None),
    service_name1: str = Form(None),
    service_desc1: str = Form(None),
    service_price1: str = Form(None),
    service_name2: str = Form(None),
    service_desc2: str = Form(None),
    service_price2: str = Form(None),
    service_name3: str = Form(None),
    service_desc3: str = Form(None),
    service_price3: str = Form(None),
    image: UploadFile = File(None),
    user=Depends(get_current_user),
):
    global _business_id_seq

    if not user:
        return RedirectResponse("/auth/login", 302)

    validate_location(sido, sigungu, dong)

    image_url = None
    if image:
        ext = image.filename.split(".")[-1] if "." in image.filename else "jpg"
        filename = f"{uuid.uuid4()}.{ext}"
        save_path = UPLOAD_DIR / filename
        with open(save_path, "wb") as f:
            shutil.copyfileobj(image.file, f)
        image_url = f"/static/uploads/{filename}"

    def as_bool(v: Optional[str]) -> bool:
        return v is not None

    menus = []
    for n, p in [
        (menu_name1, menu_price1),
        (menu_name2, menu_price2),
        (menu_name3, menu_price3),
    ]:
        if n and n.strip():
            menus.append({"name": n.strip(), "price": (p or "").strip()})

    services = []
    for n, d, p in [
        (service_name1, service_desc1, service_price1),
        (service_name2, service_desc2, service_price2),
        (service_name3, service_desc3, service_price3),
    ]:
        if n and n.strip():
            services.append(
                {
                    "name": n.strip(),
                    "desc": (d or "").strip(),
                    "price": (p or "").strip(),
                }
            )

    BUSINESSES.append(
        {
            "id": _business_id_seq,
            "kind": kind,
            "sido": sido,
            "sigungu": sigungu,
            "dong": dong,
            "category": category,
            "name": name,
            "description": description,
            "image_url": image_url,
            "owner": user,
            "approved": True if is_admin(request) else False,
            "paid": False,
            "phone": phone,
            "homepage": homepage,
            "blog": blog,
            "instagram": instagram,
            "address_road": address_road,
            "address_detail": address_detail,
            "lat": lat,
            "lng": lng,
            "hours_mon": hours_mon,
            "hours_tue": hours_tue,
            "hours_wed": hours_wed,
            "hours_thu": hours_thu,
            "hours_fri": hours_fri,
            "hours_sat": hours_sat,
            "hours_sun": hours_sun,
            "off_day": off_day,
            "opt_delivery": as_bool(opt_delivery),
            "opt_reservation": as_bool(opt_reservation),
            "opt_parking": as_bool(opt_parking),
            "opt_pet": as_bool(opt_pet),
            "opt_wifi": as_bool(opt_wifi),
            "opt_group": as_bool(opt_group),
            "menus": menus,
            "services": services,
        }
    )

    _business_id_seq += 1

    return RedirectResponse(
        f"/{kind}?sido={sido}&sigungu={sigungu}&dong={dong}", 302
    )


# =============================================================
# BUSINESS 상세
# =============================================================
@app.get("/business/{bid}", response_class=HTMLResponse)
def business_detail(
    request: Request,
    bid: int,
    user=Depends(get_current_user),
):
    b = get_business(bid)
    if not b:
        return HTMLResponse("업체 없음", 404)

    reviews = get_reviews(bid)
    avg_rating = (
        sum(r["rating"] for r in reviews) / len(reviews) if reviews else None
    )

    return templates.TemplateResponse(
        "business_detail.html",
        {
            "request": request,
            "user": user,
            "business": b,
            "reviews": reviews,
            "avg_rating": avg_rating,
            "review_count": len(reviews),
        },
    )


# =============================================================
# 리뷰
# =============================================================
@app.post("/business/{bid}/review")
def add_review(
    bid: int,
    rating: int = Form(...),
    comment: str = Form(...),
    user=Depends(get_current_user),
):
    if not user:
        return RedirectResponse("/auth/login", 302)

    if not get_business(bid):
        return HTMLResponse("업체 없음", 404)

    REVIEWS.append(
        {
            "business_id": bid,
            "username": user,
            "rating": rating,
            "comment": comment,
        }
    )

    return RedirectResponse(f"/business/{bid}", 302)


# =============================================================
# 마이페이지 — 내가 등록한 업체
# =============================================================
@app.get("/my/businesses", response_class=HTMLResponse)
def my_businesses(request: Request, user=Depends(get_current_user)):
    if not user:
        return RedirectResponse("/auth/login", 302)

    mine = [b for b in BUSINESSES if b["owner"] == user]

    return templates.TemplateResponse(
        "my_businesses.html",
        {"request": request, "user": user, "businesses": mine},
    )


# =============================================================
# BUSINESS 수정
# =============================================================
def can_edit(request: Request, b: dict) -> bool:
    u = get_current_user(request)
    return bool(u) and (u == b["owner"] or is_admin(request))


@app.get("/business/{bid}/edit", response_class=HTMLResponse)
def edit_page(
    request: Request,
    bid: int,
    user=Depends(get_current_user),
):
    b = get_business(bid)
    if not b:
        return HTMLResponse("업체 없음", 404)
    if not can_edit(request, b):
        return HTMLResponse("권한 없음", 403)

    return templates.TemplateResponse(
        "business_edit.html",
        {"request": request, "user": user, "business": b, "sido_list": CAPITAL_SIDO},
    )


@app.post("/business/{bid}/edit")
def edit_business(
    request: Request,
    bid: int,
    kind: str = Form(...),
    sido: str = Form(...),
    sigungu: str = Form(...),
    dong: str = Form(...),
    category: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    phone: str = Form(None),
    homepage: str = Form(None),
    blog: str = Form(None),
    instagram: str = Form(None),
    address_road: str = Form(None),
    address_detail: str = Form(None),
    lat: str = Form(None),
    lng: str = Form(None),
    hours_mon: str = Form(None),
    hours_tue: str = Form(None),
    hours_wed: str = Form(None),
    hours_thu: str = Form(None),
    hours_fri: str = Form(None),
    hours_sat: str = Form(None),
    hours_sun: str = Form(None),
    off_day: str = Form(None),
    opt_delivery: str = Form(None),
    opt_reservation: str = Form(None),
    opt_parking: str = Form(None),
    opt_pet: str = Form(None),
    opt_wifi: str = Form(None),
    opt_group: str = Form(None),
    menu_name1: str = Form(None),
    menu_price1: str = Form(None),
    menu_name2: str = Form(None),
    menu_price2: str = Form(None),
    menu_name3: str = Form(None),
    menu_price3: str = Form(None),
    service_name1: str = Form(None),
    service_desc1: str = Form(None),
    service_price1: str = Form(None),
    service_name2: str = Form(None),
    service_desc2: str = Form(None),
    service_price2: str = Form(None),
    service_name3: str = Form(None),
    service_desc3: str = Form(None),
    service_price3: str = Form(None),
    image: UploadFile = File(None),
    user=Depends(get_current_user),
):
    b = get_business(bid)
    if not b:
        return "업체 없음"
    if not can_edit(request, b):
        return "권한 없음"

    validate_location(sido, sigungu, dong)

    if image:
        ext = image.filename.split(".")[-1] if "." in image.filename else "jpg"
        filename = f"{uuid.uuid4()}.{ext}"
        save_path = UPLOAD_DIR / filename
        with open(save_path, "wb") as f:
            shutil.copyfileobj(image.file, f)
        b["image_url"] = f"/static/uploads/{filename}"

    def as_bool(v: Optional[str]) -> bool:
        return v is not None

    menus = []
    for n, p in [
        (menu_name1, menu_price1),
        (menu_name2, menu_price2),
        (menu_name3, menu_price3),
    ]:
        if n and n.strip():
            menus.append({"name": n.strip(), "price": (p or "").strip()})

    services = []
    for n, d, p in [
        (service_name1, service_desc1, service_price1),
        (service_name2, service_desc2, service_price2),
        (service_name3, service_desc3, service_price3),
    ]:
        if n and n.strip():
            services.append(
                {
                    "name": n.strip(),
                    "desc": (d or "").strip(),
                    "price": (p or "").strip(),
                }
            )

    b.update(
        {
            "kind": kind,
            "sido": sido,
            "sigungu": sigungu,
            "dong": dong,
            "category": category,
            "name": name,
            "description": description,
            "phone": phone,
            "homepage": homepage,
            "blog": blog,
            "instagram": instagram,
            "address_road": address_road,
            "address_detail": address_detail,
            "lat": lat,
            "lng": lng,
            "hours_mon": hours_mon,
            "hours_tue": hours_tue,
            "hours_wed": hours_wed,
            "hours_thu": hours_thu,
            "hours_fri": hours_fri,
            "hours_sat": hours_sat,
            "hours_sun": hours_sun,
            "off_day": off_day,
            "opt_delivery": as_bool(opt_delivery),
            "opt_reservation": as_bool(opt_reservation),
            "opt_parking": as_bool(opt_parking),
            "opt_pet": as_bool(opt_pet),
            "opt_wifi": as_bool(opt_wifi),
            "opt_group": as_bool(opt_group),
            "menus": menus,
            "services": services,
        }
    )

    return RedirectResponse(f"/business/{bid}", 302)


# =============================================================
# BUSINESS 삭제
# =============================================================
@app.post("/business/{bid}/delete")
def delete_business(
    request: Request,
    bid: int,
    user=Depends(get_current_user),
):
    b = get_business(bid)
    if not b:
        return "업체 없음"
    if not can_edit(request, b):
        return "권한 없음"

    global BUSINESSES, REVIEWS
    BUSINESSES = [x for x in BUSINESSES if x["id"] != bid]
    REVIEWS = [r for r in REVIEWS if r["business_id"] != bid]

    return RedirectResponse("/", 302)


# =============================================================
# ADMIN — 승인 시스템
# =============================================================
@app.get("/admin/businesses/pending", response_class=HTMLResponse)
def pending_list(request: Request, admin=Depends(admin_required)):
    items = [b for b in BUSINESSES if not b.get("approved")]
    return templates.TemplateResponse(
        "admin_pending.html",
        {"request": request, "user": admin, "businesses": items},
    )


@app.post("/admin/businesses/{bid}/approve")
def approve_business(bid: int, admin=Depends(admin_required)):
    b = get_business(bid)
    if b:
        b["approved"] = True
    return RedirectResponse("/admin/businesses/pending", 302)


@app.post("/admin/businesses/{bid}/reject")
def reject_business(bid: int, admin=Depends(admin_required)):
    global BUSINESSES, REVIEWS
    BUSINESSES = [b for b in BUSINESSES if b["id"] != bid]
    REVIEWS = [r for r in REVIEWS if r["business_id"] != bid]
    return RedirectResponse("/admin/businesses/pending", 302)


# =============================================================
# 입점비 결제 (모의)
# =============================================================
@app.post("/business/{bid}/pay-entry")
def pay_entry(
    request: Request,
    bid: int,
    user=Depends(get_current_user),
):
    if not user:
        return RedirectResponse("/auth/login", 302)

    b = get_business(bid)
    if not b:
        return "업체 없음"

    if not (b["owner"] == user or is_admin(request)):
        return "권한 없음"

    b["paid"] = True
    return RedirectResponse(f"/business/{bid}", 302)


# =============================================================
# 일반 회원가입 / 로그인
# =============================================================
@app.get("/auth/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/auth/register")
def register(
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    db: Session = Depends(get_db),
):
    if password != password2:
        return HTMLResponse("비밀번호가 일치하지 않습니다.", 400)

    existing = get_user_by_username(db, username)
    if existing:
        return HTMLResponse("이미 존재하는 아이디입니다.", 400)

    user = User(
        username=username,
        password_hash=hash_password(password),
        login_type="email",
        is_admin=(username == ADMIN_USERNAME),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    res = RedirectResponse("/", 302)
    res.set_cookie("user", username)
    if user.is_admin:
        res.set_cookie("is_admin", "1")
    return res


@app.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/auth/login")
def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        admin_user = get_user_by_username(db, username)
        if not admin_user:
            admin_user = User(
                username=username,
                password_hash=hash_password(password),
                login_type="email",
                is_admin=True,
            )
            db.add(admin_user)
            db.commit()

        res = RedirectResponse("/admin", 302)
        res.set_cookie("user", username)
        res.set_cookie("is_admin", "1")
        return res

    u = get_user_by_username(db, username)
    if not u or u.password_hash != hash_password(password):
        return HTMLResponse("로그인 실패", 400)

    db.commit()

    res = RedirectResponse("/", 302)
    res.set_cookie("user", username)
    res.delete_cookie("is_admin")
    return res


@app.get("/auth/logout")
def logout():
    res = RedirectResponse("/", 302)
    res.delete_cookie("user")
    res.delete_cookie("is_admin")
    return res


# =============================================================
# 카카오 로그인
# =============================================================
@app.get("/auth/kakao/login")
async def kakao_login():
    kakao_auth_url = (
        "https://kauth.kakao.com/oauth/authorize"
        f"?client_id={KAKAO_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        "&response_type=code"
    )
    return RedirectResponse(kakao_auth_url)


@app.get("/auth/kakao/callback", response_class=HTMLResponse)
async def kakao_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return HTMLResponse(f"카카오 로그인 에러: {error}", 400)

    if not code:
        return HTMLResponse("code 파라미터 없음", 400)

    token_url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": KAKAO_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "code": code,
    }

    async with httpx.AsyncClient() as client:
        token_res = await client.post(token_url, data=data)

    if token_res.status_code != 200:
        return HTMLResponse(f"토큰 발급 실패: {token_res.text}", 400)

    token_json = token_res.json()
    access_token = token_json.get("access_token")
    if not access_token:
        return HTMLResponse(f"토큰 발급 실패: {token_json}", 400)

    async with httpx.AsyncClient() as client:
        user_res = await client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if user_res.status_code != 200:
        return HTMLResponse(f"유저 정보 실패: {user_res.text}", 400)

    user_json = user_res.json()
    kakao_id = str(user_json.get("id"))
    account = user_json.get("kakao_account", {}) or {}
    profile = account.get("profile", {}) or {}

    email = account.get("email")
    nickname = profile.get("nickname") or "카카오사용자"

    user = get_user_by_kakao_id(db, kakao_id)

    if not user:
        base_username = f"kakao_{kakao_id}"
        username = base_username

        n = 1
        while get_user_by_username(db, username):
            username = f"{base_username}_{n}"
            n += 1

        user = User(
            username=username,
            email=email,
            kakao_id=kakao_id,
            login_type="kakao",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    res = RedirectResponse("/", 302)
    res.set_cookie("user", user.username)
    res.delete_cookie("is_admin")
    return res


# =============================================================
# ADMIN 메인
# =============================================================
@app.get("/admin", response_class=HTMLResponse)
def admin_home(
    request: Request,
    admin=Depends(admin_required),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.id.desc()).all()
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "user": admin,
            "users": users,
            "businesses": BUSINESSES,
            "news_posts": NEWS_POSTS,
            "reviews": REVIEWS,
        },
    )


# =============================================================
# manifest.json / service-worker.js
# =============================================================
@app.get("/manifest.json")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.json")


@app.get("/static/service-worker.js")
def sw():
    return FileResponse(STATIC_DIR / "service-worker.js")


