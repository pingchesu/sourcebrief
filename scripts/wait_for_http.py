from __future__ import annotations

import sys
import time
import urllib.request

url = sys.argv[1]
timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 60
deadline = time.time() + timeout
last_error = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if 200 <= response.status < 300:
                print(f"ready: {url}")
                raise SystemExit(0)
    except Exception as exc:
        last_error = exc
    time.sleep(2)
print(f"timed out waiting for {url}: {last_error}", file=sys.stderr)
raise SystemExit(1)
