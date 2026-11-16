"""Offline stand-in for the Lasna RPC, Base Sepolia RPC and Blockscout, built on recorded logs.

`FakeNet.opener` has the urllib.request.urlopen signature, so it plugs into pelitarpc.Client. Logs are
the recording in tests/fixtures/census_chain.json; block timestamps outside it follow a linear clock.
Every request is kept in `requests` so tests can check headers and window sizes.
"""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "census_chain.json"
CHAINS = json.loads((Path(__file__).resolve().parents[1] / "config" / "chains.json").read_text(encoding="utf-8"))


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class _Resp:
    def __init__(self, payload, status=200):
        self.status = status
        self.headers = {"Content-Type": "application/json"}
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeNet:
    def __init__(self, fixture=None):
        self.fx = fixture or load_fixture()
        self.requests = []
        self.latest = {name: self.fx[name]["latest"] for name in ("lasna", "base-sepolia")}
        self.eth_calls = {}  # (rpc url, to, data) -> hex result
        self.balances = {}  # (rpc url, address) -> wei
        self.extra_logs = {}  # rpc url -> list of logs for eth_getLogs on non-biller addresses
        self.fail = False
        self.by_rpc = {CHAINS["chains"][n]["rpc"]: n for n in ("lasna", "base-sepolia")}

    def calls(self, method):
        """Every JSON-RPC call item with this method, single or inside a batch."""
        out = []
        for r in self.requests:
            body = r["body"]
            for item in body if isinstance(body, list) else [body] if body else []:
                if item.get("method") == method:
                    out.append(item)
        return out

    def block_ts(self, name, number):
        clock = self.fx[name]["clock"]
        return int(clock["anchor_ts"] + (number - clock["anchor_block"]) * clock["block_seconds"])

    def opener(self, req, timeout=None):
        headers = {k.lower(): v for k, v in req.header_items()}
        body = json.loads(req.data) if req.data else None
        self.requests.append({"url": req.full_url, "headers": headers, "body": body})
        if self.fail:
            raise OSError("network down (test)")
        if req.full_url.startswith(CHAINS["chains"]["base-sepolia"]["blockscout_api"]):
            return _Resp(self._blockscout(req.full_url))
        name = self.by_rpc[req.full_url]
        if isinstance(body, list):
            return _Resp([self._rpc(name, req.full_url, item) for item in body])
        return _Resp(self._rpc(name, req.full_url, body))

    def _blockscout(self, url):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        rows = [
            r
            for r in self.fx["base-sepolia"]["blockscout"].get(q["topic0"], [])
            if int(q["fromBlock"]) <= int(r["blockNumber"], 16) <= int(q["toBlock"])
        ]
        page, size = int(q.get("page", 1)), int(q.get("offset", 1000))
        rows = rows[(page - 1) * size : page * size]
        return {"status": "1" if rows else "0", "message": "OK" if rows else "No logs found", "result": rows}

    def _rpc(self, name, url, item):
        method, params = item["method"], item.get("params") or []
        result = None
        if method == "eth_blockNumber":
            result = hex(self.latest[name])
        elif method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            if number <= self.latest[name]:
                result = {"number": params[0], "timestamp": hex(self.block_ts(name, number))}
        elif method == "eth_getLogs":
            result = self._logs(name, url, params[0])
        elif method == "eth_call":
            result = self.eth_calls.get((url, params[0]["to"].lower(), params[0]["data"]), "0x" + "0" * 64)
        elif method == "eth_getBalance":
            result = hex(self.balances.get((url, params[0].lower()), 0))
        elif method == "rnk_getFilters":
            result = self.fx["filters"]
        return {"jsonrpc": "2.0", "id": item["id"], "result": result}

    def _logs(self, name, url, flt):
        lo, hi = int(flt["fromBlock"], 16), int(flt["toBlock"], 16)
        if flt["address"].lower() == CHAINS["chains"][name]["biller"].lower():
            source = self.fx[name].get("logs", [])
        else:
            source = self.extra_logs.get(url, [])
        wanted = set(flt["topics"][0])
        return [
            lg
            for lg in source
            if lo <= int(lg["blockNumber"], 16) <= hi
            and lg["topics"][0] in wanted
            and lg["address"].lower() == flt["address"].lower()
        ]
