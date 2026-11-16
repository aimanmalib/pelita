"""Small JSON-RPC and HTTP client shared by Pelita's Python tools (standard library only).

Every request carries the User-Agent from config/chains.json: the public Base Sepolia RPC and
Blockscout answer 403 to the default Python agent. The opener is injectable so tests run offline.
"""

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_config(name):
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return json.load(f)


class RpcError(Exception):
    pass


class Client:
    def __init__(self, user_agent, timeout=30, opener=None):
        if not user_agent or not user_agent.strip():
            raise ValueError("user_agent is required")
        self.user_agent = user_agent
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._id = 0

    def request(self, url, body=None, headers=None):
        """Returns (status, headers dict with lower-case keys, decoded body text)."""
        hdrs = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if body is not None:
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
        with self._open(req, timeout=self.timeout) as resp:
            head = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, head, resp.read().decode("utf-8")

    def call(self, url, method, params=None):
        """One JSON-RPC call. Raises RpcError with the node's message on an error reply."""
        self._id += 1
        _, _, text = self.request(url, {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []})
        reply = json.loads(text)
        if "error" in reply:
            raise RpcError(str(reply["error"].get("message", reply["error"])))
        return reply["result"]
