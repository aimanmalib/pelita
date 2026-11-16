"""Thin wrapper over Foundry's `forge` and `cast` for Pelita's chain scripts (standard library only).

Every transaction is sent by `forge create` or `cast send` with a Foundry keystore. The key never passes through this
code: it is chosen with `--account <name>` (or `--keystore <path>`) and unlocked with `--password-file`, so it is not
in argv, logs or the repository. Foundry is called by absolute path (`$HOME/.foundry/bin`) because cron and
non-interactive shells do not load it into PATH.
"""

import json
import os
import subprocess
from decimal import Decimal
from pathlib import Path

WEI = Decimal(10) ** 18


class FoundryError(Exception):
    pass


def to_wei(amount):
    """'0.05' ether units -> integer wei. Rejects negatives and sub-wei precision."""
    wei = Decimal(str(amount)) * WEI
    if wei < 0 or wei != wei.to_integral_value():
        raise ValueError(f"bad amount: {amount}")
    return int(wei)


def auth_from_env(env=None):
    """Keystore flags from the environment. Defaults: account `pelita`, password file ~/.config/pelita/keystore.pass.

    PELITA_KEYSTORE (a keystore file path) wins over PELITA_ACCOUNT (a name in ~/.foundry/keystores). A missing password
    file is left out, so Foundry asks for the password itself (deploy-your-own.sh).
    """
    env = os.environ if env is None else env
    home = env.get("HOME", str(Path.home()))
    if env.get("PELITA_KEYSTORE"):
        args = ["--keystore", env["PELITA_KEYSTORE"]]
    else:
        args = ["--account", env.get("PELITA_ACCOUNT", "pelita")]
    pw = env.get("PELITA_PASSWORD_FILE", f"{home}/.config/pelita/keystore.pass")
    if pw and Path(pw).is_file():
        args += ["--password-file", pw]
    return args


def bin_dir(env=None):
    env = os.environ if env is None else env
    return Path(env.get("FOUNDRY_BIN", f"{env.get('HOME', str(Path.home()))}/.foundry/bin"))


class Foundry:
    def __init__(self, auth, bindir=None, cwd=None, run=None):
        self.auth = list(auth)
        self.bindir = Path(bindir) if bindir else bin_dir()
        self.cwd = cwd
        self._run = run or self._subprocess

    def _subprocess(self, argv):
        p = subprocess.run(argv, cwd=self.cwd, capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            # stderr from forge/cast never contains the key; keep only its last lines.
            tail = "\n".join((p.stderr or p.stdout).strip().splitlines()[-5:])
            raise FoundryError(f"{Path(argv[0]).name} {argv[1]} failed: {tail}")
        return p.stdout

    def cast(self, *args):
        return self._run([str(self.bindir / "cast"), *map(str, args)]).strip()

    def forge(self, *args):
        return self._run([str(self.bindir / "forge"), *map(str, args)]).strip()

    # Reads (no key).
    def chain_id(self, rpc):
        return int(self.cast("chain-id", "--rpc-url", rpc))

    def code(self, rpc, address):
        return self.cast("code", address, "--rpc-url", rpc)

    def has_code(self, rpc, address):
        return bool(address) and self.code(rpc, address) not in ("", "0x")

    def balance(self, rpc, address):
        return int(self.cast("balance", address, "--rpc-url", rpc))

    def call(self, rpc, to, sig, *args):
        return self.cast("call", to, sig, *args, "--rpc-url", rpc)

    def receipt_block(self, rpc, tx):
        return int(self.cast("receipt", tx, "blockNumber", "--rpc-url", rpc), 0)

    # Writes (keystore).
    def create(self, rpc, contract, args, value_wei=0):
        argv = ["create", contract, "--rpc-url", rpc, *self.auth, "--broadcast", "--json"]
        if value_wei:
            argv += ["--value", str(value_wei)]
        if args:
            argv += ["--constructor-args", *args]
        out = json.loads(_last_json(self.forge(*argv)))
        return out["deployedTo"], out["transactionHash"]

    def send(self, rpc, to, sig=None, args=(), value_wei=0):
        argv = ["send", to]
        if sig:
            argv += [sig, *args]
        argv += ["--rpc-url", rpc, *self.auth, "--json"]
        if value_wei:
            argv += ["--value", str(value_wei)]
        receipt = json.loads(_last_json(self.cast(*argv)))
        if receipt.get("status") not in ("0x1", 1, "1"):
            raise FoundryError(f"transaction reverted: {receipt.get('transactionHash')}")
        return receipt["transactionHash"]

    def address(self):
        return self.cast("wallet", "address", *self.auth)

    def verify(self, address, contract, chain_id, ctor_sig, args, verifier, verifier_url=None):
        argv = ["verify-contract", address, contract, "--chain-id", chain_id, "--verifier", verifier]
        if verifier_url:
            argv += ["--verifier-url", verifier_url]
        if ctor_sig:
            argv += ["--constructor-args", self.cast("abi-encode", ctor_sig, *args)]
        self.forge(*argv)


def _last_json(text):
    """forge/cast may print warnings before the JSON object; return the JSON part."""
    start = text.find("{")
    if start < 0:
        raise FoundryError(f"no JSON in output: {text[-200:]}")
    return text[start:]
