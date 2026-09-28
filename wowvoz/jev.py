"""JEV (TypeSafe's decision model, typesafe/jev-1.13) through OpenRouter's decisions
endpoint: one request, a short timeout, no retries, no redirects. Any failure is
None, and the phrase is simply not acted on."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

URL = "https://openrouter.ai/api/alpha/decisions"


def api_key(key_file: str) -> str:
    env = os.environ.get("OPENROUTER_API_KEY", "")
    if env and not re.search(r"\s", env):
        return env
    path = os.path.expanduser(key_file)
    try:
        if os.path.islink(path) or os.path.getsize(path) > 8192:
            return ""
        raw = open(path, encoding="utf-8").read()
    except OSError:
        return ""
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_]+)\s*=\s*(.*)$", line)
        if m:
            if m.group(1) != "OPENROUTER_API_KEY":
                continue
            v = m.group(2).strip().strip("'\"")
            return "" if re.search(r"\s", v) else v
        return "" if re.search(r"\s", line) else line
    return ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        raise urllib.error.HTTPError(a[1] if len(a) > 1 else "", 310, "redirect refused", None, None)


def decide(body: dict, key_file: str, timeout: float) -> tuple[dict | None, str, int]:
    """(answer, error, ms)."""
    key = api_key(key_file)
    if not key:
        return None, "no OpenRouter key", 0
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    started = time.monotonic()
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as res:
            data = res.read(1 << 20)
        return json.loads(data), "", int((time.monotonic() - started) * 1000)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}", int((time.monotonic() - started) * 1000)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return None, type(e).__name__, int((time.monotonic() - started) * 1000)
