"""Small JSON-RPC and HTTP client shared by Pelita's Python tools (standard library only).

Every request carries the User-Agent from config/chains.json: the public Base Sepolia RPC and
Blockscout answer 403 to the default Python agent. The opener is injectable so tests run offline.

JSON-RPC calls to a chain's `rpc` may move to the chain's `rpc_fallback` list (config/chains.json) when
an endpoint refuses (HTTP 429 or 5xx, a timeout or connection error, or a "request limit" reply): each
endpoint is tried once per call, with no sleep, and a client that saw a refusal starts on the endpoint
that answered for the rest of its life (one indexer run). Errors name the host (ADR 0004).
"""

import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def load_config(name):
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return json.load(f)


class RpcError(Exception):
    pass


class Unavailable(OSError):
    """No endpoint served the request. Not an RpcError on purpose: callers read RpcError as the node's own
    answer (a pruned block, a reverted call) and may turn it into a dash; a refusal must fail the step."""


class _Refused(Exception):
    """An endpoint that refused to serve (rate limit, server error, network): the next endpoint may answer."""


LIMIT_CODES = (-32005, -32007)  # JSON-RPC "limit exceeded" / "request limit reached" (Lasna, 24 Nov)


def host(url):
    return urlparse(url).hostname or url


def fallbacks(chains_cfg):
    """{primary rpc url: [fallback urls]} for every chain that lists `rpc_fallback`."""
    return {c["rpc"]: list(c["rpc_fallback"]) for c in chains_cfg["chains"].values() if c.get("rpc_fallback")}


def client_for(chains_cfg, timeout=30, opener=None):
    return Client(chains_cfg["user_agent"], timeout=timeout, opener=opener, fallbacks=fallbacks(chains_cfg))


def _limit_error(reply):
    err = reply.get("error") if isinstance(reply, dict) else None
    return isinstance(err, dict) and (err.get("code") in LIMIT_CODES or "limit" in str(err.get("message", "")).lower())


class Client:
    def __init__(self, user_agent, timeout=30, opener=None, fallbacks=None):
        if not user_agent or not user_agent.strip():
            raise ValueError("user_agent is required")
        self.user_agent = user_agent
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._id = 0
        self._fallbacks = fallbacks or {}
        self._start = {}  # primary url -> endpoint that answered after a refusal

    def endpoints(self, url):
        urls = [url] + [u for u in self._fallbacks.get(url, []) if u != url]
        first = self._start.get(url)
        return [first] + [u for u in urls if u != first] if first in urls else urls

    def _post_once(self, url, body):
        try:
            _, _, text = self.request(url, body)
        except urllib.error.HTTPError as err:
            if err.code == 429 or err.code >= 500:
                raise _Refused(f"HTTP {err.code}") from err
            raise Unavailable(f"{host(url)}: HTTP {err.code} {err.reason}") from err
        except OSError as err:  # timeouts and connection errors
            raise _Refused(f"{type(err).__name__}: {err}") from err
        reply = json.loads(text)
        replies = reply if isinstance(reply, list) else [reply]
        if any(_limit_error(r) for r in replies):
            limited = next(r for r in replies if _limit_error(r))
            raise _Refused(f"{limited['error'].get('code')} {limited['error'].get('message')}")
        return reply

    def _post(self, url, body):
        """POST a JSON-RPC body to `url`, moving once through its fallbacks on a refusal."""
        refusals = []
        for endpoint in self.endpoints(url):
            try:
                reply = self._post_once(endpoint, body)
            except _Refused as err:
                refusals.append(f"{host(endpoint)}: {err}")
                continue
            if refusals:
                self._start[url] = endpoint
            return endpoint, reply
        raise Unavailable(" | ".join(refusals))

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
        endpoint, reply = self._post(url, {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []})
        if "error" in reply:
            raise RpcError(f"{host(endpoint)}: {reply['error'].get('message', reply['error'])}")
        return reply["result"]

    def batch(self, url, calls):
        """One JSON-RPC batch request; `calls` = [(method, params)]. Results in call order; any error raises."""
        if not calls:
            return []
        body = []
        for method, params in calls:
            self._id += 1
            body.append({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        endpoint, replies = self._post(url, body)
        if not isinstance(replies, list):
            raise RpcError(f"{host(endpoint)}: {replies.get('error', replies)}")
        by_id = {r.get("id"): r for r in replies}
        out = []
        for item in body:
            reply = by_id.get(item["id"])
            if reply is None or "error" in reply:
                raise RpcError(f"{host(endpoint)}: {(reply or {}).get('error', 'missing batch reply')}")
            out.append(reply["result"])
        return out
