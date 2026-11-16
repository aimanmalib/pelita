"""Offline unit tests for the chain-script helpers (no anvil, no network)."""

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


if __name__ == "__main__":
    unittest.main()
