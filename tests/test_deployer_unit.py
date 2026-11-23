"""Offline unit tests for the chain-script helpers (no anvil, no network)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import deployer  # noqa: E402
import foundry  # noqa: E402


class HelpersTest(unittest.TestCase):
    def test_to_wei(self):
        self.assertEqual(foundry.to_wei("0.05"), 5 * 10**16)
        self.assertEqual(foundry.to_wei("12"), 12 * 10**18)
        for bad in ("-1", "0.0000000000000000001"):
            with self.assertRaises(ValueError):
                foundry.to_wei(bad)

    def test_auth_never_carries_a_key_and_defaults_to_pelita_keystore(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".config" / "pelita").mkdir(parents=True)
            (Path(home) / ".config" / "pelita" / "keystore.pass").write_text("x")
            args = foundry.auth_from_env({"HOME": home})
            self.assertEqual(args[:2], ["--account", "pelita"])
            self.assertEqual(args[2], "--password-file")
            self.assertNotIn("--private-key", args)
            self.assertEqual(foundry.auth_from_env({"HOME": home, "PELITA_KEYSTORE": "/k"})[:2], ["--keystore", "/k"])
            # deploy-your-own: no password file -> Foundry prompts.
            self.assertEqual(foundry.auth_from_env({"HOME": home, "PELITA_ACCOUNT": "me", "PELITA_PASSWORD_FILE": ""}),
                             ["--account", "me"])

    def test_last_bool_reads_cast_tuples(self):
        self.assertTrue(deployer.last_bool("(5318007, 0xAb, 50000000000000000 [5e16], 0, false, true)"))
        self.assertFalse(deployer.last_bool("(0, 0x0, 0, 0, 0, 0, 0, 0, false, false)"))
        self.assertTrue(deployer.last_bool("0x476F\n0xabc\n400000\ntrue"))
        with self.assertRaises(deployer.DeployError):
            deployer.last_bool("0x")

    def test_rpc_override_from_environment(self):
        chain = {"rpc": "https://sepolia.base.org"}
        self.assertEqual(deployer.rpc_for("base-sepolia", chain, {}), "https://sepolia.base.org")
        self.assertEqual(deployer.rpc_for("base-sepolia", chain, {"PELITA_RPC_BASE_SEPOLIA": "http://x"}), "http://x")

    def test_last_json_skips_warnings_before_the_object(self):
        self.assertEqual(foundry._last_json('Warning: x\n{"a": 1}'), '{"a": 1}')
        with self.assertRaises(foundry.FoundryError):
            foundry._last_json("nothing")


class VerifyTest(unittest.TestCase):
    """Source verification failing never fails the deploy, and is retried on the next run."""

    def make(self, out, fail):
        class F:
            calls = []

            def verify(self, *a):
                F.calls.append(a)
                if fail:
                    raise foundry.FoundryError("explorer down")

        chains = {"chains": {
            "lasna": {"aktif": True, "reactive": True, "chain_id": 5318007, "rpc": "r", "biller": "0x8"},
            "base-sepolia": {"aktif": True, "reactive": False, "chain_id": 84532, "rpc": "d", "biller": "0x4"},
        }}
        cfg = {"deploy": {"verifiers": {"lasna": {"verifier": "sourcify"}}}}
        d = deployer.Deployer(F(), chains, cfg, {"lasna": "r", "base-sepolia": "d"}, out, log=lambda *_: None)
        d.r.contracts["keeper"] = {"address": "0xK", "kind": "keeper", "args": ["1", "2"], "block": 7, "verified": False}
        return d, F

    def test_failure_is_recorded_not_raised_then_retried(self):
        with tempfile.TemporaryDirectory() as out:
            d, F = self.make(out, fail=True)
            d.verify_all()
            self.assertFalse(d.r.contracts["keeper"]["verified"])
            d2, F2 = self.make(out, fail=False)
            d2.verify_all()
            self.assertEqual(d2.r.contracts["keeper"]["verified"], "sourcify")
            self.assertEqual(F2.calls[-1][2], 5318007)
            # Base Sepolia has no verifier configured here: nothing was attempted for it.
            self.assertTrue(all(c[0] == "0xK" for c in F2.calls))


class VerifyOnlyTest(unittest.TestCase):
    """--verify-only reads chain ids and verifies; it never creates, sends or transfers."""

    def test_sends_nothing_and_records_the_source_link(self):
        class F:
            verified = []

            def chain_id(self, rpc):
                return {"r": 5318007, "d": 84532}[rpc]

            def verify(self, address, *a):
                F.verified.append(address)

            def __getattr__(self, name):  # create/send/balance would mean a transaction path ran
                raise AssertionError(f"verify-only called {name}")

        chains = {"chains": {
            "lasna": {"aktif": True, "reactive": True, "chain_id": 5318007, "rpc": "r", "biller": "0x8"},
            "base-sepolia": {"aktif": True, "reactive": False, "chain_id": 84532, "rpc": "d", "biller": "0x4"},
        }}
        cfg = {"deploy": {"verifiers": {
            "lasna": {"verifier": "sourcify", "link": "https://v.example/{chain_id}/{address}"},
            "base-sepolia": {"verifier": "blockscout"},
        }}}
        with tempfile.TemporaryDirectory() as out:
            d = deployer.Deployer(F(), chains, cfg, {"lasna": "r", "base-sepolia": "d"}, out, log=lambda *_: None)
            d.r.contracts["keeper"] = {"address": "0xK", "kind": "keeper", "args": ["1", "2"], "block": 7,
                                       "verified": False}
            d.d.contracts["beacon"] = {"address": "0xB", "kind": "beacon", "args": ["1", "2", "3"], "block": 9,
                                       "verified": False}
            self.assertEqual(d.verify_only(), [])
            self.assertEqual(sorted(F.verified), ["0xB", "0xK"])
            self.assertEqual(d.r.contracts["keeper"]["source"], "https://v.example/5318007/0xK")
            self.assertNotIn("source", d.d.contracts["beacon"])  # no link template: no link invented
            saved = json.loads((Path(out) / "lasna.json").read_text())
            self.assertEqual(saved["contracts"]["keeper"]["verified"], "sourcify")


class ExplorerCheckTest(unittest.TestCase):
    """A rate-limited status poll must not leave a verified contract marked unverified, nor re-submit it."""

    def run_with(self, explorer):
        class F:
            calls = []

            def verify(self, address, *a):
                F.calls.append(address)

        chains = {"chains": {
            "lasna": {"aktif": True, "reactive": True, "chain_id": 5318007, "rpc": "r", "biller": "0x8"},
            "base-sepolia": {"aktif": True, "reactive": False, "chain_id": 84532, "rpc": "d", "biller": "0x4"},
        }}
        check = {"url": "https://x.example/{chain_id}/{address}", "field": "ok", "values": [True]}
        cfg = {"deploy": {"verifiers": {"base-sepolia": {"verifier": "blockscout", "check": check}}}}
        urls = []

        def ask(url):
            urls.append(url)
            return explorer(url)

        with tempfile.TemporaryDirectory() as out:
            d = deployer.Deployer(F(), chains, cfg, {"lasna": "r", "base-sepolia": "d"}, out, log=lambda *_: None,
                                  explorer=ask)
            d.d.contracts["lantern"] = {"address": "0xL", "kind": "lantern", "args": ["0x4", "0xF"], "block": 3,
                                        "verified": False}
            d.verify_all()
            return d.d.contracts["lantern"]["verified"], F.calls, urls

    def test_already_verified_on_explorer_is_recorded_without_submitting(self):
        verified, calls, urls = self.run_with(lambda url: {"ok": True})
        self.assertEqual((verified, calls, urls), ("blockscout", [], ["https://x.example/84532/0xL"]))

    def test_explorer_error_or_no_falls_back_to_forge(self):
        def boom(url):
            raise OSError("429")

        for explorer in (boom, lambda url: {"ok": False}, lambda url: ["unexpected"]):
            verified, calls, _ = self.run_with(explorer)
            self.assertEqual((verified, calls), ("blockscout", ["0xL"]))


class CallbackGasTest(unittest.TestCase):
    """Base Sepolia's proxy rejected a 100000-gas delivery with InsufficientGas (23 Nov, ADR 0008): a demo pair with
    such a limit can never be lit. The deployer refuses it, and replaces a Flicker whose fixed gas is too low."""

    CHAINS = {"chains": {
        "lasna": {"aktif": True, "reactive": True, "chain_id": 5318007, "rpc": "r", "biller": "0x8"},
        "base-sepolia": {"aktif": True, "reactive": False, "chain_id": 84532, "rpc": "d", "biller": "0x4",
                         "callback_gas_min": 200000},
    }}

    def fake(self):
        class F:
            sent, created = [], []
            wards = {"0xold"}

            def has_code(self, rpc, address):
                return True

            def create(self, rpc, contract, args, value):
                F.created.append((contract, args))
                return f"0xnew{len(F.created)}", f"0xtx{len(F.created)}"

            def receipt_block(self, rpc, tx):
                return 1

            def call(self, rpc, to, sig, *args):
                if sig.startswith("ward("):
                    return "(1, 0x, 0, 0, 0, 0, 0, 0, true, true)" if args[1] in F.wards else "(false, false)"
                return "0x0000000000000000000000000000000000000000"

            def send(self, rpc, to, sig, args, value=0):
                F.sent.append((to, sig, list(args)))
                return "0xsent"

        return F

    def test_gas_below_the_proxy_floor_is_refused(self):
        with tempfile.TemporaryDirectory() as out:
            d = deployer.Deployer(self.fake()(), self.CHAINS, {}, {"lasna": "r", "base-sepolia": "d"}, out,
                                  log=lambda *_: None)
            with self.assertRaises(deployer.DeployError):
                d.check_callback_gas(100000)
            d.check_callback_gas(300000)

    def test_flicker_with_other_fixed_gas_is_replaced_retired_and_released(self):
        F = self.fake()
        with tempfile.TemporaryDirectory() as out:
            d = deployer.Deployer(F(), self.CHAINS, {}, {"lasna": "r", "base-sepolia": "d"}, out, log=lambda *_: None)
            old = {"address": "0xold", "kind": "flicker", "args": ["84532", "0xB", "100000"], "block": 5}
            d.r.contracts["flicker_guarded"] = dict(old)
            d.r.contracts["keeper"] = {"address": "0xK", "kind": "keeper", "args": ["1", "2"], "block": 4}
            new = d.ensure_contract(d.r, "flicker_guarded", "flicker", [84532, "0xB", 300000])
            self.assertEqual(new, "0xnew1")
            self.assertEqual(d.r.data["retired"], [dict(old, key="flicker_guarded")])
            # Same fixed args: kept, nothing created.
            self.assertEqual(d.ensure_contract(d.r, "flicker_guarded", "flicker", [84532, "0xB", 300000]), "0xnew1")
            self.assertEqual(len(F.created), 1)
            # A beacon value that has a setter is still kept, not redeployed.
            d.d.contracts["beacon"] = {"address": "0xB", "kind": "beacon", "args": ["600", "40", "86400"], "block": 2}
            self.assertEqual(d.ensure_contract(d.d, "beacon", "beacon", [300, 40, 86400]), "0xB")
            d.release_retired("0xK", d.r, 5318007)
            self.assertEqual(F.sent, [("0xK", "release(uint256,address)", ["5318007", "0xold"])])
            F.wards.clear()  # released: a second run sends nothing
            d.release_retired("0xK", d.r, 5318007)
            self.assertEqual(len(F.sent), 1)
            d.r.save("keeper", "flicker")
            saved = json.loads((Path(out) / "lasna.json").read_text())
            self.assertEqual([w["address"] for w in saved["wards"]], ["0xnew1"])
            self.assertEqual(saved["retired"][0]["address"], "0xold")


if __name__ == "__main__":
    unittest.main()
