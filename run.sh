#!/usr/bin/env bash
# اجرای چکر. روی سرور بدون گرافیک خودکار از Xvfb استفاده می‌کند.
set -e
COMBO="${1:-combos.txt}"
if [ -n "$DISPLAY" ]; then
  python3 checker.py "$COMBO" "${@:2}"
else
  xvfb-run -a --server-args="-screen 0 1366x900x24" python3 checker.py "$COMBO" "${@:2}"
fi
