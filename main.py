import os, hashlib, secrets, hmac
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY") or "").strip()
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY (server-side) must be set in .env")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

UPLOAD_DIR = ROOT / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="MarketOS", version="1.3-supabase")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
SECRET = os.getenv("MARKETOS_SESSION_SECRET", "").strip()
ADMIN_KEY = os.getenv("MARKETOS_ADMIN_KEY", "").strip()

# Keep convenient local development, but refuse known-insecure defaults in production.
if APP_ENV == "production":
    if len(SECRET) < 32 or len(ADMIN_KEY) < 24:
        raise RuntimeError(
            "Production requires MARKETOS_SESSION_SECRET (32+ characters) "
            "and MARKETOS_ADMIN_KEY (24+ characters)."
        )
else:
    SECRET = SECRET or "LOCAL_DEVELOPMENT_ONLY_NOT_FOR_PUBLIC_DEPLOYMENT"
    ADMIN_KEY = ADMIN_KEY or "change-this-admin-key"

def rows(table, **filters):
    q = supabase.table(table).select("*")
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.execute().data or []

def one(table, **filters):
    data = rows(table, **filters)
    return data[0] if data else None

def insert(table, data):
    result = supabase.table(table).insert(data).execute()
    return result.data[0] if result.data else None

def update(table, data, **filters):
    q = supabase.table(table).update(data)
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.execute().data or []

def delete(table, **filters):
    q = supabase.table(table).delete()
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.execute().data or []

def ordered(table, order="id", desc=True, **filters):
    q = supabase.table(table).select("*")
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.order(order, desc=desc).execute().data or []

def pw_hash(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 180000).hex()

def pw_ok(pw, stored):
    try:
        salt, digest = stored.split("$", 1)
        return hmac.compare_digest(pw_hash(pw, salt).split("$", 1)[1], digest)
    except Exception:
        return False

def token_for(uid):
    raw = str(uid)
    return raw + "." + hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()

def current_user(request):
    try:
        raw, sig = request.cookies.get("mos_session", "").split(".", 1)
        expected = hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return one("users", id=int(raw))
    except Exception:
        return None

def render(request, name, **context):
    context["request"] = request
    return templates.TemplateResponse(request=request, name=name, context=context)

SUBSCRIPTION_DAYS = 30
PUBLIC_PATHS = {"/", "/login", "/register", "/logout", "/api/health", "/favicon.ico"}
PAYMENT_PATHS = {"/payment", "/payment/create"}

def parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None

def subscription_state(user):
    """New accounts get 30 days from registration; each owner-approved payment adds 30 days."""
    now = datetime.now(timezone.utc)
    paid_rows = ordered("payments", "id", user_id=user["id"])
    expiries = []
    for payment in paid_rows:
        if str(payment.get("status", "")).lower() != "paid":
            continue
        paid_at = parse_utc(payment.get("paid_at")) or parse_utc(payment.get("created_at"))
        if paid_at:
            expiries.append(paid_at + timedelta(days=SUBSCRIPTION_DAYS))
    latest_paid_expiry = max(expiries) if expiries else None
    registered_at = parse_utc(user.get("created_at"))
    trial_expiry = registered_at + timedelta(days=SUBSCRIPTION_DAYS) if registered_at else None
    # A later owner-approved paid subscription takes precedence over the signup period.
    expires_at = latest_paid_expiry or trial_expiry
    active = expires_at is not None and now < expires_at
    return {
        "paid": active,
        "expired": not active,
        "trial": bool(active and latest_paid_expiry is None),
        "expires_at": expires_at,
        "days_left": max(0, (expires_at - now).days) if active else 0,
    }

@app.middleware("http")
async def allow_logged_in_access(request: Request, call_next):
    # Payment is optional for this version; login should not force users to /payment.
    return await call_next(request)


@app.get("/manifest.webmanifest")
async def pwa_manifest():
    return JSONResponse({
        "id": "/",
        "name": "MarketOS",
        "short_name": "MarketOS",
        "description": "A simple local marketplace for customers and shopkeepers.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f5f8f6",
        "theme_color": "#16834a",
        "orientation": "portrait",
        "icons": [
            {"src": "/static/icons/marketos-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/marketos-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/marketos-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        ]
    })

@app.get("/sw.js")
async def pwa_service_worker():
    script = """
self.addEventListener('install', event => { self.skipWaiting(); });
self.addEventListener('activate', event => { event.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', event => {
  // Network-only: never cache private account, dashboard, or session responses.
  if (event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request));
});
"""
    from fastapi.responses import Response
    return Response(content=script, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
def save_image(upload, prefix):
    if not upload or not upload.filename:
        return ""
    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "Image must be JPG, PNG or WEBP.")
    content = upload.file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Image size must be 5 MB or less.")
    if not content:
        return ""
    filename = f"{prefix}_{secrets.token_hex(8)}{ext}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return "/static/uploads/" + filename

def with_shop(product):
    shop = one("users", id=product.get("shopkeeper_id"))
    return {**product, "shop_name": (shop or {}).get("shop_name", ""),
            "owner_name": (shop or {}).get("name", ""),
            "shop_address": (shop or {}).get("shop_address", ""),
            "shop_status": (shop or {}).get("shop_status", "offline")}

def notification_table_ready():
    try:
        supabase.table("notifications").select("id").limit(1).execute()
        return True
    except Exception:
        return False

def add_customer_notification(customer_id, title, message, kind="order"):
    now = datetime.now().astimezone().isoformat()
    return insert("notifications", {"user_id": int(customer_id), "title": title[:120],
        "message": message[:1000], "kind": kind, "is_read": False, "created_at": now})

def get_catalogue():
    """Return products that have stock and belong to currently-online shops."""
    products = []
    for product in ordered("products", "id", desc=False):
        if not product.get("active") or int(product.get("stock") or 0) <= 0:
            continue
        item = with_shop(product)
        if item.get("shop_status") == "online":
            products.append(item)
    return products[:100]

def get_online_shops():
    return [u for u in ordered("users", "id", desc=False)
            if u.get("role") == "shopkeeper" and u.get("shop_status") == "online"][:12]

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render(request, "index.html", user=current_user(request),
                  shops=get_online_shops(), products=get_catalogue())

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render(request, "auth.html", mode="register", error=None, registered=False)

@app.post("/register")
def register(request: Request, name: str=Form(...), mobile: str=Form(...), role: str=Form(...),
             password: str=Form(...), referral_code: str=Form("")):
    name = name.strip()
    mobile = "".join(c for c in mobile if c.isdigit())
    if not name or len(mobile) != 10 or len(password) < 8 or role not in ("customer", "shopkeeper"):
        return render(request, "auth.html", mode="register", error="Enter name, valid 10-digit mobile, role and password of at least 8 characters.", registered=False)
    if one("users", mobile=mobile):
        return render(request, "auth.html", mode="register", error="Mobile already registered.", registered=False)
    referral_code = referral_code.strip().upper()
    inviter = one("users", referral_code=referral_code) if referral_code else None
    if referral_code and not inviter:
        return render(request, "auth.html", mode="register", error="Referral code not found.", registered=False)
    code = secrets.token_hex(4).upper()
    while one("users", referral_code=code):
        code = secrets.token_hex(4).upper()
    now = datetime.now().astimezone().isoformat()
    user = insert("users", {"name":name,"mobile":mobile,"role":role,"password_hash":pw_hash(password),
        "referral_code":code,"referred_by":referral_code or None,"created_at":now,
        "shop_status":"offline","shop_name":""})
    if inviter and user:
        reward = 150 if inviter.get("role") == "customer" else 0
        insert("referrals", {"inviter_id":inviter["id"],"invitee_id":user["id"],"reward_amount":reward,
                             "status":"pending","created_at":now})
    return RedirectResponse("/login?registered=1", status_code=303)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "auth.html", mode="login", error=None, registered=request.query_params.get("registered") == "1")

@app.post("/login")
def login(request: Request, mobile: str=Form(...), password: str=Form(...)):
    mobile = "".join(c for c in mobile if c.isdigit())
    user = one("users", mobile=mobile)
    if not user or not pw_ok(password, user.get("password_hash", "")):
        return render(request, "auth.html", mode="login", error="Mobile or password is incorrect.", registered=False)
    # Payment is optional in this version; send every successful login to the dashboard.
    response = RedirectResponse("/dashboard", status_code=303)
    secure_cookie = os.getenv("COOKIE_SECURE", "true" if APP_ENV == "production" else "false").lower() == "true"
    response.set_cookie("mos_session", token_for(user["id"]), httponly=True, samesite="lax",
                        secure=secure_cookie, max_age=604800, path="/")
    return response

@app.get("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("mos_session")
    return response

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    referrals = []
    for r in ordered("referrals", "id", inviter_id=user["id"]):
        invitee = one("users", id=r["invitee_id"]) or {}
        referrals.append({**r,"name":invitee.get("name",""),"role":invitee.get("role","")})
    total = {"n":len(referrals),"amount":sum(int(r.get("reward_amount") or 0) for r in referrals)}
    payments = ordered("payments", "id", user_id=user["id"])
    subscription = subscription_state(user)
    products = ordered("products", "id", shopkeeper_id=user["id"]) if user["role"]=="shopkeeper" else []
    catalogue_products = get_catalogue() if user["role"]=="customer" else []
    online_shops = get_online_shops() if user["role"]=="customer" else []
    claims = ordered("reward_claims", "id", shopkeeper_id=user["id"]) if user["role"]=="shopkeeper" else []
    bookings = []
    for b in ordered("bookings", "id", shopkeeper_id=user["id"] if user["role"]=="shopkeeper" else user["id"]):
        p = one("products", id=b["product_id"]) or {}
        other = one("users", id=b["customer_id"] if user["role"]=="shopkeeper" else b["shopkeeper_id"]) or {}
        bookings.append({**b,"product_name":p.get("name",""),"price":p.get("price",0),
                         "customer_name":other.get("name",""),"customer_mobile":other.get("mobile",""),
                         "shop_name":other.get("shop_name",""),"shop_owner":other.get("name","")})
    if user["role"]=="shopkeeper":
        invited = [one("users", id=r["invitee_id"]) or {} for r in rows("referrals", inviter_id=user["id"])]
        today = date.today().isoformat()
        daily_customers = sum(1 for u in invited if u.get("role")=="customer" and str(u.get("created_at",""))[:10]==today)
        total_customers = sum(1 for u in invited if u.get("role")=="customer")
        total_shops = sum(1 for u in invited if u.get("role")=="shopkeeper")
        can_claim_customers = daily_customers >= 10 and not any(c.get("milestone")=="10_customers_day" and str(c.get("created_at",""))[:10]==today for c in claims)
        can_claim_shops = total_shops >= 2 and not any(c.get("milestone")=="2_shopkeepers" and c.get("status") in ("pending","approved","paid") for c in claims)
        return render(request,"shopkeeper_dashboard.html",user=user,products=products,claims=claims,referrals=referrals,total=total,payments=payments,bookings=bookings,daily_customers=daily_customers,total_customers=total_customers,total_shops=total_shops,can_claim_customers=can_claim_customers,can_claim_shops=can_claim_shops,subscription=subscription)
    notifications = ordered("notifications", "id", user_id=user["id"]) if notification_table_ready() else []
    return render(request,"dashboard.html",user=user,referrals=referrals,total=total,
                  payments=payments,bookings=bookings,products=catalogue_products,shops=online_shops,
                  notifications=notifications,subscription=subscription)

@app.post("/shop/profile")
def shop_profile(request: Request, shop_name: str=Form(...), shop_category: str=Form(""), shop_address: str=Form(""), shop_description: str=Form(""), shop_photo: UploadFile=File(None)):
    user=current_user(request)
    if not user or user["role"]!="shopkeeper": return RedirectResponse("/login",status_code=303)
    if not shop_name.strip(): return RedirectResponse("/dashboard?msg=shop_name_required",status_code=303)
    data={"shop_name":shop_name.strip(),"shop_category":shop_category.strip(),"shop_address":shop_address.strip(),"shop_description":shop_description.strip()}
    if shop_photo and shop_photo.filename: data["shop_photo"]=save_image(shop_photo,f"shop_{user['id']}")
    update("users",data,id=user["id"])
    return RedirectResponse("/dashboard?msg=profile_saved",status_code=303)

@app.post("/shop/status")
def shop_status(request: Request, status: str=Form(...)):
    user=current_user(request)
    if not user or user["role"]!="shopkeeper": return RedirectResponse("/login",status_code=303)
    if status not in ("online","offline"): raise HTTPException(400,"Invalid shop status")
    update("users",{"shop_status":status},id=user["id"])
    return RedirectResponse("/dashboard?msg=status_saved",status_code=303)

@app.post("/products/add")
def product_add(request: Request, name: str=Form(...), category: str=Form(""), price: float=Form(...), stock: int=Form(0), description: str=Form(""), photo: UploadFile=File(None)):
    user=current_user(request)
    if not user or user["role"]!="shopkeeper": return RedirectResponse("/login",status_code=303)
    if not name.strip() or price<0 or stock<0: raise HTTPException(400,"Product name, non-negative price and stock are required.")
    path=save_image(photo,f"product_{user['id']}") if photo and photo.filename else ""
    insert("products",{"shopkeeper_id":user["id"],"name":name.strip(),"category":category.strip(),"price":price,"stock":stock,"description":description.strip(),"photo_path":path,"active":True,"created_at":datetime.now().astimezone().isoformat()})
    return RedirectResponse("/dashboard?msg=product_added",status_code=303)

@app.post("/products/{product_id}/toggle")
def product_toggle(request: Request, product_id: int):
    user=current_user(request)
    if not user or user["role"]!="shopkeeper": return RedirectResponse("/login",status_code=303)
    p=one("products",id=product_id,shopkeeper_id=user["id"])
    if p: update("products",{"active":not bool(p.get("active"))},id=product_id,shopkeeper_id=user["id"])
    return RedirectResponse("/dashboard?msg=product_updated",status_code=303)

@app.post("/products/{product_id}/delete")
def product_delete(request: Request, product_id: int):
    user=current_user(request)
    if not user or user["role"]!="shopkeeper": return RedirectResponse("/login",status_code=303)
    delete("products",id=product_id,shopkeeper_id=user["id"])
    return RedirectResponse("/dashboard?msg=product_deleted",status_code=303)

@app.post("/rewards/claim")
def reward_claim(request: Request, milestone: str=Form(...)):
    user=current_user(request)
    if not user or user["role"]!="shopkeeper": return RedirectResponse("/login",status_code=303)
    if milestone not in ("10_customers_day","2_shopkeepers"): raise HTTPException(400,"Unknown reward milestone")
    invited=[one("users",id=r["invitee_id"]) or {} for r in rows("referrals",inviter_id=user["id"])]
    claims=rows("reward_claims",shopkeeper_id=user["id"])
    today=date.today().isoformat()
    count=sum(1 for u in invited if u.get("role")==("customer" if milestone=="10_customers_day" else "shopkeeper") and (milestone!="10_customers_day" or str(u.get("created_at",""))[:10]==today))
    exists=any(c.get("milestone")==milestone and (milestone!="10_customers_day" or str(c.get("created_at",""))[:10]==today) and (milestone!="2_shopkeepers" or c.get("status") in ("pending","approved","paid")) for c in claims)
    if count < (10 if milestone=="10_customers_day" else 2) or exists: return RedirectResponse("/dashboard?msg=claim_not_eligible",status_code=303)
    amount=150 if milestone=="10_customers_day" else 450
    now=datetime.now().astimezone().isoformat()
    insert("reward_claims",{"shopkeeper_id":user["id"],"milestone":milestone,"amount":amount,"status":"pending","note":f"{count} referrals recorded","created_at":now,"updated_at":now})
    return RedirectResponse("/dashboard?msg=claim_submitted",status_code=303)

@app.get("/owner", response_class=HTMLResponse)
def owner_controller(request: Request):
    key=request.query_params.get("key","")
    if not hmac.compare_digest(key, ADMIN_KEY): return render(request,"admin_login.html",error="Owner controller: enter admin key.")
    users = ordered("users", "id")
    subscription_users = []
    for account in users:
        state = subscription_state(account)
        subscription_users.append({**account, "subscription": state})
    return render(request,"owner_controller.html",key=key,users=users,subscription_users=subscription_users,products=ordered("products","id"),
        bookings=ordered("bookings","id"),claims=ordered("reward_claims","id"),messages=ordered("support_messages","id"),payments=ordered("payments","id"))

@app.post("/owner/subscriptions/{user_id}/approve")
def owner_subscription_approve(user_id: int, key: str = Form(...), amount: float = Form(499)):
    """Owner confirms money was received in person and grants another 30 days."""
    if not hmac.compare_digest(key, ADMIN_KEY):
        raise HTTPException(403, "Admin authorization failed")
    account = one("users", id=user_id)
    if not account:
        raise HTTPException(404, "User not found")
    if amount < 0 or amount > 1000000:
        raise HTTPException(400, "Invalid amount")
    now = datetime.now(timezone.utc).isoformat()
    insert("payments", {"user_id": user_id, "amount": amount, "status": "paid", "created_at": now, "paid_at": now})
    if notification_table_ready():
        insert("notifications", {"user_id": user_id, "title": "MarketOS subscription renewed ✅",
            "message": f"Your subscription has been approved for 30 days. Amount recorded: ₹{amount:g}.",
            "kind": "subscription", "is_read": False, "created_at": now})
    return RedirectResponse("/owner?key=" + key + "&subscription=approved", status_code=303)

@app.post("/owner/users/{user_id}/role")
def owner_user_role(user_id:int,key:str=Form(...),role:str=Form(...)):
    if not hmac.compare_digest(key,ADMIN_KEY): raise HTTPException(403,"Admin authorization failed")
    if role not in ("customer","shopkeeper"): raise HTTPException(400,"Invalid role")
    update("users",{"role":role},id=user_id)
    return RedirectResponse("/owner?key="+key,status_code=303)

@app.post("/owner/shops/{user_id}/status")
def owner_shop_status(user_id:int,key:str=Form(...),shop_status_value:str=Form(...)):
    if not hmac.compare_digest(key,ADMIN_KEY): raise HTTPException(403,"Admin authorization failed")
    if shop_status_value not in ("online","offline"): raise HTTPException(400,"Invalid shop status")
    update("users",{"shop_status":shop_status_value},id=user_id,role="shopkeeper")
    return RedirectResponse("/owner?key="+key,status_code=303)

@app.post("/owner/support/{message_id}/status")
def owner_support_status(message_id:int,key:str=Form(...),status:str=Form(...),admin_reply:str=Form("")):
    if not hmac.compare_digest(key,ADMIN_KEY): raise HTTPException(403,"Admin authorization failed")
    if status not in ("new","in_progress","replied","closed"): raise HTTPException(400,"Invalid support status")
    update("support_messages",{"status":status,"admin_reply":admin_reply.strip()[:2000],"updated_at":datetime.now().astimezone().isoformat()},id=message_id)
    return RedirectResponse("/owner?key="+key,status_code=303)

@app.get("/admin",response_class=HTMLResponse)
def admin_page(request: Request):
    if not hmac.compare_digest(request.query_params.get("key",""),ADMIN_KEY): return render(request,"admin_login.html",error=None)
    claims=[]
    for c in ordered("reward_claims","id"):
        u=one("users",id=c["shopkeeper_id"]) or {}
        claims.append({**c,"name":u.get("name",""),"mobile":u.get("mobile",""),"shop_name":u.get("shop_name","")})
    shops=[u for u in ordered("users","id") if u.get("role")=="shopkeeper"]
    return render(request,"admin.html",claims=claims,shops=shops,key=ADMIN_KEY)

@app.post("/admin/login")
def admin_login(key: str=Form(...)):
    if not hmac.compare_digest(key,ADMIN_KEY): return RedirectResponse("/admin?error=1",status_code=303)
    return RedirectResponse("/admin?key="+key,status_code=303)

@app.post("/admin/claims/{claim_id}")
def admin_claim_update(claim_id:int,key:str=Form(...),status:str=Form(...)):
    if not hmac.compare_digest(key,ADMIN_KEY) or status not in ("approved","paid","rejected"): raise HTTPException(403,"Admin authorization failed")
    update("reward_claims",{"status":status,"updated_at":datetime.now().astimezone().isoformat()},id=claim_id)
    return RedirectResponse("/admin?key="+key,status_code=303)

@app.post("/book/{product_id}")
def book_product(request:Request,product_id:int,quantity:int=Form(1),customer_note:str=Form("")):
    user=current_user(request)
    if not user: return RedirectResponse("/login?next=book",status_code=303)
    if user["role"]!="customer": return RedirectResponse("/dashboard?msg=customer_account_required",status_code=303)
    if quantity<1 or quantity>100: raise HTTPException(400,"Quantity must be between 1 and 100.")
    p=one("products",id=product_id)
    shop=one("users",id=(p or {}).get("shopkeeper_id")) if p else None
    if not p or not p.get("active") or int(p.get("stock") or 0)<=0 or not shop or shop.get("shop_status")!="online": return RedirectResponse("/?msg=product_unavailable",status_code=303)
    if quantity>int(p.get("stock") or 0): return RedirectResponse("/?msg=quantity_exceeds_stock",status_code=303)
    now=datetime.now().astimezone().isoformat()
    insert("bookings",{"customer_id":user["id"],"product_id":product_id,"shopkeeper_id":shop["id"],"quantity":quantity,"customer_note":customer_note.strip()[:500],"status":"pending","created_at":now,"updated_at":now})
    return RedirectResponse("/dashboard?msg=booking_submitted",status_code=303)

@app.post("/bookings/{booking_id}/status")
def booking_status(request:Request,booking_id:int,status:str=Form(...),eta_minutes:int=Form(15)):
    user=current_user(request)
    if not user or user["role"]!="shopkeeper": return RedirectResponse("/login",status_code=303)
    if status not in ("accepted","rejected","completed"): raise HTTPException(400,"Invalid booking status")
    if eta_minutes < 1 or eta_minutes >= 30: raise HTTPException(400,"ETA must be under 30 minutes")
    booking=one("bookings",id=booking_id,shopkeeper_id=user["id"])
    if not booking: raise HTTPException(404,"Booking not found")
    from datetime import timedelta
    now=datetime.now().astimezone(); data={"status":status,"updated_at":now.isoformat()}
    if status == "accepted":
        eta_at=now+timedelta(minutes=eta_minutes)
        old_note=(booking.get("customer_note") or "").strip()
        data["customer_note"]=(old_note + f" | Shop update: accepted; ready in {eta_minutes} minutes around {eta_at.strftime('%I:%M %p')}").strip(" |")
    update("bookings",data,id=booking_id,shopkeeper_id=user["id"])
    try:
        shopname=user.get("shop_name") or user.get("name") or "Shop"
        if status == "accepted":
            eta_at=now+timedelta(minutes=eta_minutes)
            msg=f"{shopname} ne aapka order accept kar liya hai. Kripya {eta_minutes} minute mein, lagbhag {eta_at.strftime('%I:%M %p')} par ready/collect karne aayein."
            add_customer_notification(booking["customer_id"],"Order accepted",msg,"order")
        elif status == "rejected":
            add_customer_notification(booking["customer_id"],"Order update",f"{shopname} aapka order accept nahi kar payi. Details ke liye shop se contact karein.","order")
        else:
            add_customer_notification(booking["customer_id"],"Order completed",f"{shopname} ne aapka order complete mark kar diya hai.","order")
    except Exception:
        pass
    return RedirectResponse("/dashboard?msg=booking_updated",status_code=303)

@app.post("/notifications/{notification_id}/read")
def notification_read(request: Request, notification_id: int):
    user=current_user(request)
    if not user: return RedirectResponse("/login",status_code=303)
    if notification_table_ready(): update("notifications", {"is_read": True}, id=notification_id, user_id=user["id"])
    return RedirectResponse("/dashboard",status_code=303)

@app.post("/support/message")
def support_message(request:Request,sender_name:str=Form(""),sender_mobile:str=Form(""),subject:str=Form(""),message:str=Form(...)):
    user=current_user(request)
    sender_name=user["name"] if user else sender_name.strip()
    sender_mobile=user["mobile"] if user else "".join(c for c in sender_mobile if c.isdigit())
    message=message.strip()
    if not sender_name or not message or len(message)>2000: return RedirectResponse("/?msg=message_required",status_code=303)
    now=datetime.now().astimezone().isoformat()
    insert("support_messages",{"sender_id":user["id"] if user else None,"sender_name":sender_name[:100],"sender_mobile":sender_mobile[:10],"subject":subject.strip()[:120],"message":message,"status":"new","created_at":now,"updated_at":now})
    return RedirectResponse("/?msg=message_sent",status_code=303)

@app.get("/admin/messages",response_class=HTMLResponse)
def admin_messages(request:Request):
    key=request.query_params.get("key","")
    if not hmac.compare_digest(key,ADMIN_KEY): return render(request,"admin_login.html",error="Please enter admin key.")
    return render(request,"admin_messages.html",messages=ordered("support_messages","id"),key=key)

@app.post("/admin/messages/{message_id}/reply")
def admin_message_reply(message_id:int,key:str=Form(...),status:str=Form("replied"),admin_reply:str=Form("")):
    if not hmac.compare_digest(key,ADMIN_KEY): raise HTTPException(403,"Admin authorization failed")
    if status not in ("new","in_progress","replied","closed"): raise HTTPException(400,"Invalid message status")
    update("support_messages",{"status":status,"admin_reply":admin_reply.strip()[:2000],"updated_at":datetime.now().astimezone().isoformat()},id=message_id)
    return RedirectResponse("/admin/messages?key="+key,status_code=303)

@app.get("/payment",response_class=HTMLResponse)
def payment_page(request:Request):
    user=current_user(request)
    if not user: return RedirectResponse("/login",status_code=303)
    amount=300 if user["role"]=="customer" else 1299
    state=subscription_state(user)
    return render(request,"payment.html",user=user,amount=amount,upi_id=os.getenv("MARKETOS_UPI_ID","YOUR-MERCHANT-UPI@BANK"),created=request.query_params.get("created"),trial_expired=state["expired"],days_left=state["days_left"],paid=state["paid"],subscription_expires_at=state["expires_at"])

@app.post("/payment/create")
def payment_create(request:Request):
    user=current_user(request)
    if not user: return RedirectResponse("/login",status_code=303)
    amount=300 if user["role"]=="customer" else 1299
    p=insert("payments",{"user_id":user["id"],"amount":amount,"status":"pending","created_at":datetime.now().astimezone().isoformat()})
    return RedirectResponse(f"/payment?created={p['id']}",status_code=303)

@app.get("/terms",response_class=HTMLResponse)
def terms(request:Request): return render(request,"terms.html",user=current_user(request))

@app.get("/api/health")
def health():
    try:
        supabase.table("users").select("id").limit(1).execute()
        return {"app":"MarketOS","status":"ok","database":"supabase","payment_mode":"demo_pending_only"}
    except Exception:
        return JSONResponse(status_code=503,content={"app":"MarketOS","status":"error","database":"supabase_unreachable"})
