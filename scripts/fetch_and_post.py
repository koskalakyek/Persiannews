"""
ربات اخبار بازار ایران
------------------------
هر بار اجرا:
  ۱) از منابع RSS تعریف‌شده در sources.json اخبار تازه را می‌گیرد
  ۲) بر اساس کلیدواژه یا برچسب always_include فقط اخبار مرتبط با اقتصاد/بازار ایران را فیلتر می‌کند
  ۳) هر خبر جدید را به Gemini API می‌دهد تا ترجمه/خلاصه کامل + تحلیل تاثیر بر بازار ایران تولید کند
  ۴) نتیجه را به یک کانال تلگرام ارسال می‌کند
  ۵) شناسه خبرهای ارسال‌شده را در seen.json ذخیره می‌کند تا دوباره تکرار نشوند

این اسکریپت با GitHub Actions به‌صورت زمان‌بندی‌شده (هر ساعت) اجرا می‌شود.
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from dateutil import parser as dateparser

from price_ticker import build_price_header

# ---------- تنظیمات قابل تغییر از طریق متغیرهای محیطی ----------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

# نام مدل Gemini. اگر این مدل در آینده حذف/جایگزین شد، در ai.google.dev/gemini-api/docs/models
# نام مدل رایگان جدید را ببین و همین‌جا یا با یک Secret به نام GEMINI_MODEL جایگزین کن.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "90"))
MAX_ARTICLES_PER_RUN = int(os.environ.get("MAX_ARTICLES_PER_RUN", "10"))
GEMINI_MIN_INTERVAL_SECONDS = float(os.environ.get("GEMINI_MIN_INTERVAL_SECONDS", "7"))
MAX_SEEN_IDS = 6000

SOURCES_FILE = "sources.json"
SEEN_FILE = "seen.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IranMarketNewsBot/1.0)"}


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_id(entry):
    raw = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_published(entry):
    for key in ("published", "updated", "created"):
        if entry.get(key):
            try:
                dt = dateparser.parse(entry[key])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return None


def matches_keywords(text, keywords):
    text_low = text.lower()
    return any(kw.lower() in text_low for kw in keywords)


def collect_candidates(sources_cfg, seen_ids):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=LOOKBACK_MINUTES)
    fa_keywords = sources_cfg.get("keywords_fa", [])
    en_keywords = sources_cfg.get("keywords_en", [])

    candidates = []
    for src in sources_cfg["sources"]:
        try:
            resp = requests.get(src["url"], headers=HEADERS, timeout=20)
            parsed = feedparser.parse(resp.content)
        except Exception as e:
            log(f"⚠️  خطا در دریافت فید «{src['name']}»: {e}")
            continue

        for entry in parsed.entries:
            eid = make_id(entry)
            if eid in seen_ids:
                continue

            published = get_published(entry)
            if published and published < cutoff:
                continue  # خیلی قدیمی است

            title = entry.get("title", "")
            summary = re.sub("<[^<]+?>", "", entry.get("summary", "") or entry.get("description", ""))
            check_text = f"{title} {summary}"

            keywords = fa_keywords if src.get("lang") == "fa" else en_keywords
            relevant = src.get("always_include", False) or matches_keywords(check_text, keywords)
            if not relevant:
                continue

            candidates.append(
                {
                    "id": eid,
                    "title": title,
                    "summary": summary[:2500],
                    "link": entry.get("link", ""),
                    "published": published.isoformat() if published else "نامشخص",
                    "source_name": src["name"],
                    "tier": src.get("tier", ""),
                }
            )

    # قدیمی‌ترین‌ها اول ارسال شوند تا ترتیب زمانی در کانال حفظ شود
    candidates.sort(key=lambda c: c["published"])
    return candidates


def build_prompt(item):
    return f"""تو یک تحلیلگر اقتصادی و بازار مالی هستی که برای مخاطب ایرانی، اخبار موثر بر بازار و تصمیم‌گیری مالی را تحلیل می‌کنی.

اطلاعات خام خبر (ممکن است انگلیسی یا فارسی باشد):
عنوان: {item['title']}
منبع: {item['source_name']} (سطح اعتبار: {item['tier']})
لینک: {item['link']}
تاریخ انتشار: {item['published']}
متن/خلاصه خام: {item['summary']}

وظیفه تو:
۱. اگر خبر انگلیسی یا غیرفارسی است، آن را کامل و روان به فارسی برگردان.
۲. مشخص کن این خبر بیشتر «اقتصادی/بازاری» است یا «سیاسی/ژئوپلیتیک» (یا هر دو).
۳. یک خلاصه کامل و دقیق (نه سطحی، حدود ۱۵۰ تا ۲۵۰ کلمه) از محتوای خبر بنویس طوری‌که خواننده بدون باز کردن لینک همه نکات کلیدی را متوجه شود.
۴. در بخش جداگانه‌ای با عنوان «تحلیل و تاثیر بر بازار»، در ۴ تا ۶ جمله توضیح بده این خبر چه تاثیری می‌تواند بر اقتصاد ایران، نرخ ارز، بورس تهران، طلا/سکه یا تصمیم مالی یک فرد عادی در ایران داشته باشد. اخبار سیاسی/نظامی/منطقه‌ای (مثل تحولات اسرائیل، غزه، لبنان، تنگه هرمز، تحریم‌ها، روابط ایران و قدرت‌های بزرگ) را هم از زاویه تاثیرشان بر ریسک بازار، نرخ ارز و قیمت نفت تحلیل کن، حتی اگر مستقیماً «خبر اقتصادی» نباشند.
۵. اگر محتوای خبر بیشتر شبیه شایعه، گمانه‌زنی یا تاییدنشده است، حتما در پایان تحلیل با عبارت «⚠️ این خبر هنوز به‌طور رسمی تایید نشده و نیاز به احتیاط دارد.» هشدار بده.
۶. لحن تحلیل بی‌طرف و حرفه‌ای باشد؛ این تحلیل توصیه مالی قطعی نیست، بلکه کمک به تصمیم‌گیری آگاهانه‌تر است.

خروجی را دقیقاً با همین قالب HTML (سازگار با تلگرام) بده، بدون هیچ متن یا توضیح اضافه قبل یا بعد از آن، و بدون Markdown (فقط تگ‌های b, i, a مجاز است):

<b>📰 [عنوان خبر به فارسی]</b>
🏷 دسته: [اقتصادی/بازاری یا سیاسی/ژئوپلیتیک]
🏛 منبع: {item['source_name']}
🗓 {item['published']}

[خلاصه کامل خبر به فارسی]

<b>🔍 تحلیل و تاثیر بر بازار:</b>
[تحلیل]

🔗 <a href="{item['link']}">مشاهده خبر اصلی</a>
━━━━━━━━━━━━━━━"""


def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1000},
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
                json=payload,
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                parts = data["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts).strip()
            elif resp.status_code == 429:
                wait = 15 * (attempt + 1)
                log(f"⏳ محدودیت نرخ Gemini (429). {wait} ثانیه صبر می‌کنم...")
                time.sleep(wait)
            else:
                log(f"⚠️  خطای Gemini ({resp.status_code}): {resp.text[:300]}")
                return None
        except Exception as e:
            log(f"⚠️  خطای اتصال به Gemini: {e}")
            time.sleep(5)
    return None


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text if len(text) <= 4000 else text[:3900] + "…",
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code == 200:
        return True
    log(f"⚠️  خطای ارسال به تلگرام ({resp.status_code}): {resp.text[:300]}")
    # تلاش دوم: بدون HTML، اگر مشکل از تگ‌های ناقص باشد
    plain = re.sub("<[^<]+?>", "", text)
    payload["text"] = plain[:4000]
    payload["parse_mode"] = None
    resp2 = requests.post(url, json=payload, timeout=30)
    return resp2.status_code == 200


def main():
    missing = [
        name
        for name, val in [
            ("GEMINI_API_KEY", GEMINI_API_KEY),
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("TELEGRAM_CHANNEL_ID", TELEGRAM_CHANNEL_ID),
        ]
        if not val
    ]
    if missing:
        log(f"❌ متغیرهای محیطی زیر تنظیم نشده‌اند: {', '.join(missing)}")
        sys.exit(1)

    sources_cfg = load_json(SOURCES_FILE, {"sources": [], "keywords_fa": [], "keywords_en": []})
    seen_state = load_json(SEEN_FILE, {"seen_ids": []})
    seen_ids = set(seen_state.get("seen_ids", []))

    candidates = collect_candidates(sources_cfg, seen_ids)
    log(f"🔎 {len(candidates)} خبر جدید و مرتبط پیدا شد.")

    if not candidates:
        log("چیزی برای ارسال نیست. پایان.")
        return

    log("💹 در حال دریافت قیمت‌های لحظه‌ای برای نوار بالای پیام...")
    price_header = build_price_header()

    sent_count = 0
    for item in candidates[:MAX_ARTICLES_PER_RUN]:
        log(f"➡️  در حال پردازش: {item['title'][:80]}")
        prompt = build_prompt(item)
        result_text = call_gemini(prompt)
        time.sleep(GEMINI_MIN_INTERVAL_SECONDS)

        if not result_text:
            log("   ✗ تحلیل Gemini ناموفق بود؛ در اجرای بعدی دوباره تلاش می‌شود.")
            continue

        message = f"{price_header}\n\n{result_text}"
        ok = send_to_telegram(message)
        if ok:
            log("   ✓ با موفقیت به تلگرام ارسال شد.")
            seen_ids.add(item["id"])
            sent_count += 1
        else:
            log("   ✗ ارسال به تلگرام ناموفق بود؛ در اجرای بعدی دوباره تلاش می‌شود.")

        # ذخیره تدریجی وضعیت تا در صورت قطع اجرا، پیشرفت از دست نرود
        seen_list = list(seen_ids)[-MAX_SEEN_IDS:]
        save_json(SEEN_FILE, {"seen_ids": seen_list})

    log(f"✅ پایان اجرا. {sent_count} خبر ارسال شد.")


if __name__ == "__main__":
    main()
