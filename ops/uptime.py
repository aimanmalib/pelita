#!/usr/bin/env python3
"""Pelita uptime watch (PRD 4.11 step 3): cron PELITA-UPTIME every 5 minutes.

One GET of the public page per run. `UPTIME_FAILS_BEFORE_WARN` failures in a row (deploy/site.env) = one warning
through ~/bin/notify.sh; the first success after that = one info line. Nothing else is sent, so a long outage is
one message, not one every 5 minutes. State: state/uptime.json. Texts: config/pelita.json alerts.text.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops"))
from indexer import notify_sh, read_json, write_json_atomic  # noqa: E402


def site_env(path):
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def fetch(url, user_agent, timeout=25):
    """Status code of one GET (0 = no answer)."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(1)
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0


def step(state, code, fails_before_warn):
    """New state and the message kind to send ('site_down', 'site_up' or None)."""
    fails = 0 if code == 200 else state.get("fails", 0) + 1
    down = state.get("down", False)
    kind = None
    if code == 200 and down:
        kind, down = "site_up", False
    elif fails >= fails_before_warn and not down:
        kind, down = "site_down", True
    return {"fails": fails, "down": down, "last_code": code}, kind


def run(root=ROOT, get=fetch, notify=notify_sh, now=time.time):
    env = site_env(root / "deploy" / "site.env")
    cfg = json.loads((root / "config" / "pelita.json").read_text(encoding="utf-8"))
    ua = json.loads((root / "config" / "chains.json").read_text(encoding="utf-8"))["user_agent"] + " uptime"
    url = f"https://{env['DOMAIN']}/"
    path = root / "state" / "uptime.json"
    state = read_json(path, {})
    code = get(url, ua)
    new, kind = step(state, code, int(env["UPTIME_FAILS_BEFORE_WARN"]))
    new["last_run"] = int(now())
    if kind:
        text = cfg["alerts"]["text"][kind].format(url=url, code=code, fails=new["fails"])
        if notify(text, "warn" if kind == "site_down" else "info") != 0:
            new["down"] = state.get("down", False)  # not delivered: try again next run
    write_json_atomic(path, new)
    return 0


if __name__ == "__main__":
    sys.exit(run())
