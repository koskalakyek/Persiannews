"""
این اسکریپت را قبل از راه‌اندازی نهایی ربات، یک بار به‌صورت دستی اجرا کن:

    python scripts/validate_sources.py

هدف: بررسی اینکه آدرس RSS هر منبع در sources.json واقعاً بالا و معتبر است
و حداقل چند خبر برمی‌گرداند. آدرس فیدهای سایت‌های خبری (به‌خصوص ایرانی)
گاهی تغییر می‌کند؛ منابعی که اینجا FAIL می‌شوند را اصلاح یا حذف کن.
"""

import json
import sys

import feedparser
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IranMarketNewsBot/1.0)"}


def main():
    with open("sources.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    ok, fail = 0, 0
    for src in data["sources"]:
        name, url = src["name"], src["url"]
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            parsed = feedparser.parse(resp.content)
            n = len(parsed.entries)
            if resp.status_code == 200 and n > 0:
                print(f"✅ OK   ({n:3d} خبر)  {name}  -> {url}")
                ok += 1
            else:
                print(f"❌ FAIL (status={resp.status_code}, entries={n})  {name}  -> {url}")
                fail += 1
        except Exception as e:
            print(f"❌ FAIL (خطا: {e})  {name}  -> {url}")
            fail += 1

    print(f"\nجمع‌بندی: {ok} فید سالم / {fail} فید ناموفق از {ok + fail}")
    if fail:
        print("منابع ناموفق را در sources.json اصلاح یا حذف کن.")
        sys.exit(1)


if __name__ == "__main__":
    main()
