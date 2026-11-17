#!/usr/bin/env python3
"""Pelita indexer (PRD 4.6): read-only, no key, one pass per cron run (PELITA-INDEKS, every 2 minutes).

Each run: incremental dark/lit census per active chain (block cursor), fleet status in one batch per
chain, Pelita's own events, rnk_getFilters at most every `filters_interval_seconds`; then an atomic
write of state/public/snapshot.json and alerts through ~/bin/notify.sh, at most once a day per kind.
An RPC failure marks the run failed in state/larian.jsonl and keeps the previous snapshot; there is no
retry loop. After `rpc_failures_before_warn` failures in a row, one warning.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "ops"))
import census  # noqa: E402
import fleet  # noqa: E402
import pelitarpc  # noqa: E402

FAILURES = (pelitarpc.RpcError, OSError, ValueError, KeyError, TypeError)
KEEP_EVENTS = 200


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def notify_sh(message, level):
    """Production notifier: ~/bin/notify.sh with an exit code that reflects delivery."""
    env = dict(os.environ, NOTIFY_KOD_KELUAR="1")
    cmd = [os.path.expanduser("~/bin/notify.sh"), message, level]
    return subprocess.run(cmd, env=env, timeout=60, check=False).returncode


class Indexer:
    def __init__(self, root, client, now=time.time, notify=notify_sh):
        self.root = Path(root)
        self.client = client
        self.now = now
        self.notify = notify
        self.chains = json.loads((self.root / "config" / "chains.json").read_text(encoding="utf-8"))
        self.cfg = json.loads((self.root / "config" / "pelita.json").read_text(encoding="utf-8"))
        self.events_cfg = json.loads((self.root / "config" / "events.json").read_text(encoding="utf-8"))
        self.state_dir = self.root / "state"
        self.state_path = self.state_dir / "indexer.json"
        self.snapshot_path = self.state_dir / "public" / "snapshot.json"

    # ---- census -------------------------------------------------------------------------------
    def update_census(self, state, name, reader, latest):
        cs = state["census"].get(name)
        if cs is None:
            first = reader.block_at(census.since_ts(self.cfg), latest)
            cs = {"from_block": first, "cursor": first - 1, "events": []}
        if latest > cs["cursor"]:
            seen = {(e["tx"], e["log_index"]) for e in cs["events"]}
            new = [e for e in reader.fetch(cs["cursor"] + 1, latest) if (e["tx"], e["log_index"]) not in seen]
            cs["events"].extend(new)
            cs["cursor"] = latest
        state["census"][name] = cs
        as_of = reader.block_time(cs["cursor"])
        debts = census.debt_reader(reader, cs["cursor"], self.chains["selectors"])
        return census.census_result(reader.chain, cs["from_block"], cs["cursor"], as_of, cs["events"], debts)

    # ---- fleet --------------------------------------------------------------------------------
    def update_fleet(self, state, name, chain, dep, reader, latest):
        fs = state["fleet"]
        own, wards = fleet.read_status(self.client, chain, self.chains["selectors"], dep)
        cursor = fs["cursors"].get(name, int(dep.get("deploy_block", latest)) - 1)
        if latest > cursor:
            new = fleet.read_events(self.client, chain, dep, self.events_cfg, cursor + 1, latest)
            fs["events"].extend(fleet.add_times(new, reader))
            fs["events"] = fs["events"][-KEEP_EVENTS:]
            fs["cursors"][name] = latest
        now = int(self.now())
        for w in wards:
            key = f"{name}:{w['address']}"
            if w["debt_wei"] > 0:
                fs["dark_since"].setdefault(key, now)
                w["dark_seconds"] = now - fs["dark_since"][key]
            else:
                fs["dark_since"].pop(key, None)
        return {"own": own, "wards": wards}

    # ---- alerts -------------------------------------------------------------------------------
    def alert(self, state, kind, level, **fields):
        today = datetime.fromtimestamp(self.now(), timezone.utc).strftime("%Y-%m-%d")
        sent = state["alerts"]
        if sent.get(kind) == today:
            return False
        rc = self.notify(self.cfg["alerts"]["text"][kind].format(**fields), level)
        if rc == 0:
            sent[kind] = today
        return rc == 0

    def check_fleet_alerts(self, state, fleet_view):
        a = self.cfg["alerts"]
        low_mark = Decimal(self.cfg["keeper"]["low_mark"]) * fleet.WEI
        for name, view in fleet_view.items():
            own = view["own"]
            if own["role"] == "keeper":
                if own["debt_wei"] > 0:
                    self.alert(state, "keeper_debt", "critical", debt=fleet.ether(own["debt_wei"]))
                if own["balance_wei"] < low_mark:
                    detail = f"Keeper Lasna {fleet.ether(own['balance_wei'])} < {self.cfg['keeper']['low_mark']}"
                    self.alert(state, "tank_low", "warn", detail=detail)
            else:
                refill = Decimal(self.cfg["wards"].get(name, {}).get("refill", "0")) * fleet.WEI
                if own["balance_wei"] < refill * a["base_tank_min_refills"]:
                    detail = f"Tank {name} {fleet.ether(own['balance_wei'])} < {a['base_tank_min_refills']} refills"
                    self.alert(state, "tank_low", "warn", detail=detail)
            for w in view["wards"]:
                if w["role"] == "guarded" and w.get("dark_seconds", 0) > a["ward_dark_minutes"] * 60:
                    reason = fleet.last_reason(state["fleet"]["events"], w["address"])
                    self.alert(
                        state, "ward_dark", "warn",
                        address=w["address"], chain=name, minutes=a["ward_dark_minutes"], reason=reason,
                    )

    # ---- one run ------------------------------------------------------------------------------
    def load_state(self):
        state = read_json(self.state_path, {})
        state.setdefault("census", {})
        state.setdefault("fleet", {"cursors": {}, "events": [], "dark_since": {}})
        state.setdefault("filters", {"checked_at": 0, "summary": None})
        state.setdefault("alerts", {})
        state.setdefault("failures", 0)
        return state

    def collect(self, state):
        names = census.active_chains(self.chains)
        deployments = fleet.load_deployments(self.root, names)
        snap = {"census": {}, "fleet": {}, "events": [], "filters": None, "demo": None}
        for name in names:
            chain = self.chains["chains"][name]
            reader = census.ChainReader(self.client, chain, self.chains["topics"])
            latest = reader.latest_block()
            snap["census"][name] = self.update_census(state, name, reader, latest)
            if name in deployments:
                snap["fleet"][name] = self.update_fleet(state, name, chain, deployments[name], reader, latest)
                demo = fleet.read_demo(self.client, name, chain, self.chains["selectors"], deployments[name])
                snap["demo"] = snap["demo"] or demo
        interval = self.cfg["indexer"]["filters_interval_seconds"]
        reactive = next((n for n in names if self.chains["chains"][n].get("reactive")), None)
        if reactive and self.now() - state["filters"]["checked_at"] >= interval:
            chain = self.chains["chains"][reactive]
            result = self.client.call(chain["rpc"], "rnk_getFilters")
            state["filters"] = {
                "checked_at": int(self.now()),
                "summary": fleet.summarize_filters(result, self.chains["topics"], chain["biller"]),
            }
        snap["filters"] = state["filters"]
        snap["events"] = state["fleet"]["events"][-50:]
        return snap

    def run(self):
        started = self.now()
        state = self.load_state()
        record = {"ts": int(started)}
        try:
            snap = self.collect(state)
        except FAILURES as err:
            state["failures"] += 1
            record.update(ok=False, error=f"{type(err).__name__}: {err}"[:300])
            limit = self.cfg["alerts"]["rpc_failures_before_warn"]
            if state["failures"] == limit:
                self.alert(state, "rpc_failures", "warn", count=limit, error=record["error"][:120])
            rc = 1
        else:
            state["failures"] = 0
            snap["generated_at"] = int(self.now())
            write_json_atomic(self.snapshot_path, snap)
            if snap["fleet"]:
                self.check_fleet_alerts(state, snap["fleet"])
            record["ok"] = True
            rc = 0
        record["seconds"] = round(self.now() - started, 2)
        write_json_atomic(self.state_path, state)
        with open(self.state_dir / "larian.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return rc


def main():
    chains = pelitarpc.load_config("chains.json")
    return Indexer(ROOT, pelitarpc.Client(chains["user_agent"])).run()


if __name__ == "__main__":
    sys.exit(main())
