"""
این اسکریپت را یک‌بار به‌صورت دستی اجرا کن تا مطمئن شوی قیمت‌ها درست خوانده می‌شوند:

    python scripts/test_prices.py

اگر یکی از مقادیر «نامشخص» بود، JSON خام زیر همین خروجی چاپ می‌شود؛
با نگاه به آن، شرط‌های find_item در price_ticker.py را با نام فیلدهای واقعی تطبیق بده.
"""

import json

from price_ticker import build_price_header, fetch_json, GOLD_CURRENCY_URL, BRENT_URL

print("=== خروجی نهایی نوار قیمت ===")
print(build_price_header())

print("\n=== برای دیباگ: نمونه خام JSON دلار/طلا (اگر عددی نامشخص بود این را بررسی کن) ===")
raw = fetch_json(GOLD_CURRENCY_URL)
print(json.dumps(raw, ensure_ascii=False, indent=2)[:3000] if raw else "دریافت نشد")

print("\n=== برای دیباگ: نمونه خام JSON نفت برنت ===")
raw2 = fetch_json(BRENT_URL)
print(json.dumps(raw2, ensure_ascii=False, indent=2)[:1500] if raw2 else "دریافت نشد")
