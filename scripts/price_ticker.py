"""
نوار قیمت لحظه‌ای بالای هر پیام
--------------------------------
این ماژول قیمت‌ها را از API واقعی می‌گیرد و هرگز به هوش مصنوعی اجازه
نمی‌دهد قیمت حدس بزند (برای جلوگیری از عدد نادرست/توهم‌زده).

منابع:
- دلار و طلای ۱۸ عیار بازار ایران: BrsApi.ir (وب‌سرویس رایگان و بدون نیاز به کلید)
  https://brsapi.ir/free-api-gold-currency-webservice/
- نفت برنت: Yahoo Finance (نماد BZ=F)، یک منبع عمومی و پرکاربرد بدون نیاز به کلید

⚠️ نکته مهم: ساختار دقیق JSON این وب‌سرویس‌ها می‌تواند در طول زمان تغییر کند.
قبل از استفاده نهایی، حتما یک‌بار scripts/test_prices.py را اجرا کن تا مطمئن شوی
اعداد درست استخراج می‌شوند؛ اگر عددی «نامشخص» بود، ساختار JSON را در همان اسکریپت
چاپ کن و شرط‌های find_item در همین فایل را با فیلدهای واقعی تطبیق بده.
"""

import requests
from datetime import datetime, timedelta, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IranMarketNewsBot/1.0)"}
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

GOLD_CURRENCY_URL = "https://brsapi.ir/FreeTsetmcBourseApi/Api_Free_Gold_Currency_v2.json"
BRENT_URL = "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?interval=1d&range=1d"

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_fa_digits(s):
    return s.translate(PERSIAN_DIGITS)


def fmt_number(n):
    return to_fa_digits(f"{n:,.0f}")


def fetch_json(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def flatten_items(data):
    """هر ساختار JSON (دیکشنری از لیست‌ها یا یک لیست ساده) را به یک لیست تخت از دیکشنری‌ها تبدیل می‌کند."""
    items = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                items.extend([x for x in v if isinstance(x, dict)])
    elif isinstance(data, list):
        items = [x for x in data if isinstance(x, dict)]
    return items


def find_item(items, include_all=(), include_any=(), exclude=()):
    for it in items:
        blob = " ".join(str(it.get(k, "")) for k in ("symbol", "name", "name_en")).lower()
        if any(ex.lower() in blob for ex in exclude):
            continue
        if include_all and not all(inc.lower() in blob for inc in include_all):
            continue
        if include_any and not any(inc.lower() in blob for inc in include_any):
            continue
        if not include_all and not include_any:
            continue
        return it
    return None


def get_usd_and_gold18():
    usd_toman, gold18_toman = None, None
    data = fetch_json(GOLD_CURRENCY_URL)
    if not data:
        return None, None

    items = flatten_items(data)

    usd_item = find_item(
        items,
        include_any=("usd", "دلار آمریکا", "دلار امریکا"),
        exclude=("تتر", "usdt", "سکه", "coin"),
    )
    gold_item = find_item(
        items,
        include_any=("18", "هجده"),
        exclude=("سکه", "coin", "24", "21", "20", "نیم", "ربع"),
    )
    # اگر فیلتر بالا برای طلا خیلی سخت‌گیرانه بود و همزمان کلمه gold/طلا هم لازم است:
    if gold_item is None:
        gold_item = find_item(items, include_all=("18",))

    def extract_price(it):
        if not it:
            return None
        for key in ("price", "value", "price_toman", "sell", "close"):
            if key in it and it[key] not in (None, ""):
                try:
                    return float(str(it[key]).replace(",", ""))
                except ValueError:
                    continue
        return None

    usd_raw = extract_price(usd_item)
    gold_raw = extract_price(gold_item)

    # این وب‌سرویس معمولا قیمت را به ریال می‌دهد؛ اگر عدد خیلی بزرگ بود، به تومان تبدیل می‌کنیم.
    if usd_raw:
        usd_toman = usd_raw / 10 if usd_raw > 300000 else usd_raw
    if gold_raw:
        gold18_toman = gold_raw / 10 if gold_raw > 3000000 else gold_raw

    return usd_toman, gold18_toman


def get_brent_price():
    data = fetch_json(BRENT_URL)
    try:
        return data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except Exception:
        return None


def build_price_header():
    usd_toman, gold18_toman = get_usd_and_gold18()
    brent = get_brent_price()
    now_str = to_fa_digits(datetime.now(TEHRAN_TZ).strftime("%H:%M"))

    usd_line = f"{fmt_number(usd_toman)} تومان" if usd_toman else "نامشخص"
    gold_line = f"{fmt_number(gold18_toman)} تومان/گرم" if gold18_toman else "نامشخص"
    brent_line = f"${brent:,.2f}" if brent else "نامشخص"
    brent_line = to_fa_digits(brent_line) if brent else brent_line

    return (
        "<b>📊 داشبورد بازار | لحظه‌ای</b>\n"
        f"💵 دلار (بازار آزاد): <code>{usd_line}</code>\n"
        f"🥇 طلای ۱۸ عیار: <code>{gold_line}</code>\n"
        f"🛢 نفت برنت: <code>{brent_line}</code>\n"
        f"🕒 ساعت {now_str} به وقت تهران\n"
        "━━━━━━━━━━━━━━━"
    )
