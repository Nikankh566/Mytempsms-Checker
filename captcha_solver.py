"""
captcha_solver.py  —  حل کپچای Cloudflare Turnstile بدون API key
=================================================================
روش: مرورگر واقعی (Chromium) از طریق DrissionPage + کلیک انسانی روی چک‌باکس
      و انتظار برای تولید توکن توسط خودِ Cloudflare.
      توکن از input[name=cf-turnstile-response] خوانده می‌شود و یک‌بارمصرف است.

نکتهٔ حیاتی دربارهٔ محیط اجرا
------------------------------
Cloudflare Turnstile به «انگشت‌نگاری مرورگر» و «شهرت IP» حساس است.
در محیط سرور/دیتاسنتر و صفحه‌نمایش مجازی (Xvfb/headless) نتیجهٔ سرویس
"Verification failed" است و هیچ توکنی تولید نمی‌شود.
برای حل واقعی باید این ماژول روی یک ماشین با IP خانگی/شبکهٔ کاربر و
مرورگر واقعی اجرا شود (مثلاً از طریق Desktop App یا Remote Control).

در لینوکس بدون گرافیک (VPS با IP تمیز) می‌توان از Xvfb استفاده کرد:
    xvfb-run -a --server-args="-screen 0 1366x900x24" python3 checker.py combos.txt

نکته: چون boilerplate دامنه حساس است، این ماژول فقط بوم‌شناسی حل کپچا را
پیاده‌سازی می‌کند و هیچ‌گونه دور زدن سرور/تقلب سمت سرور انجام نمی‌دهد؛
صرفاً همان تعامل انسانی مرورگر را شبیه‌سازی می‌کند.
"""

import time
import random
from DrissionPage import ChromiumPage, ChromiumOptions

LOGIN_URL = "https://mytempsms.com/login"
WIDGET_SELECTOR = "#turnstile-box"
TOKEN_INPUT = "input[name=cf-turnstile-response]"

STEALTH_JS = """
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
window.chrome = window.chrome || {runtime:{}};
Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
"""

UA_WINDOWS = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class TurnstileSolver:
    """مرورگر پایدار که توکن Turnstile صفحهٔ لاگین mytempsms را تولید می‌کند."""

    def __init__(self, browser_path="/usr/bin/chromium", headless=False,
                 display_size=(1366, 900), user_agent=UA_WINDOWS, timeout=70,
                 verbose=True):
        self.timeout = timeout
        self.verbose = verbose
        self._page = None
        self._launch(browser_path, headless, display_size, user_agent)

    # ------------------------------------------------------------------ #
    def _log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    def _launch(self, browser_path, headless, display_size, user_agent):
        co = ChromiumOptions()
        if browser_path:
            co.set_browser_path(browser_path)
        co.headless(headless)
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-dev-shm-usage")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--window-size=%d,%d" % display_size)
        co.set_argument("--lang=en-US")
        co.set_user_agent(user_agent)
        co.auto_port()
        self._page = ChromiumPage(co)
        self._page.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=STEALTH_JS)
        self._load()

    def _load(self):
        self._page.get(LOGIN_URL, timeout=30)
        time.sleep(random.uniform(5, 8))

    # ------------------------------------------------------------------ #
    def _token_value(self):
        try:
            return self._page.run_js(
                "return document.querySelector(%r)?.value || ''" % TOKEN_INPUT
            )
        except Exception:
            return ""

    def _reset_widget(self):
        """آزادسازی ویجت برای تولید توکن بعدی (توکن یک‌بارمصرف است)."""
        try:
            self._page.run_js(
                "if(window.turnstile){try{window.turnstile.reset()}catch(e){}}"
            )
        except Exception:
            pass
        time.sleep(random.uniform(1.5, 2.5))

    def _human_click(self, tx, ty):
        """حرکت ماوس شبه‌انسانی و کلیک روی چک‌باکس (مختصات «سند»)."""
        acts = self._page.actions
        steps = random.randint(3, 5)
        x, y = tx - random.randint(140, 220), ty - random.randint(50, 90)
        for i in range(1, steps + 1):
            nx = int(x + (tx - x) * i / steps) + random.randint(-6, 6)
            ny = int(y + (ty - y) * i / steps) + random.randint(-6, 6)
            acts.move_to((nx, ny), duration=random.uniform(0.2, 0.45))
        acts.move_to((tx, ty), duration=random.uniform(0.25, 0.45))
        time.sleep(random.uniform(0.25, 0.6))
        acts.click()

    def solve(self, retries=3):
        """کلیک روی چک‌باکس و برگرداندن توکن. در صورت شکست None."""
        for attempt in range(1, retries + 1):
            self._reset_widget()
            try:
                box = self._page.ele(WIDGET_SELECTOR, timeout=6)
            except Exception:
                box = None
            if box is None:
                self._log("  [!] ویجت پیدا نشد؛ بارگذاری مجدد صفحه")
                self._load()
                continue

            box.scroll.to_see()
            time.sleep(random.uniform(1.2, 2.0))
            doc = box.rect.location          # مختصات سند (نه viewport!)
            tx, ty = doc[0] + 25, doc[1] + 31  # محل چک‌باکس
            self._log("  [*] حل کپچا (تلاش %d) در (%d,%d)" % (attempt, tx, ty))
            self._human_click(tx, ty)

            deadline = time.time() + self.timeout
            while time.time() < deadline:
                tok = self._token_value()
                if tok:
                    self._log("  [+] توکنگرفته شد (len=%d)" % len(tok))
                    return tok
                time.sleep(1.0)
            self._log("  [!] توکن تولید نشد (Turnstile رد کرد / Verification failed)")
        return None

    # ------------------------------------------------------------------ #
    def close(self):
        try:
            self._page.quit()
        except Exception:
            pass
