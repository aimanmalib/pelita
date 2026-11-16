"""scripts/deploy.sh against two local anvil chains that carry the real chain ids (Lasna 5318007, Base Sepolia 84532).

The Lasna system contract address gets the MockSystem test double (`anvil_setCode`), the Base Sepolia callback proxy
gets MockBiller. The key is a fresh random Foundry keystore made for the test, funded with `anvil_setBalance`: no key
is stored anywhere. Skipped when anvil is not installed.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "ops"))
sys.path.insert(0, str(ROOT / "scripts"))
import deployer  # noqa: E402
import fleet  # noqa: E402
import foundry  # noqa: E402
import pelitarpc  # noqa: E402

BIN = foundry.bin_dir()
ANVIL = BIN / "anvil"
CHAINS = pelitarpc.load_config("chains.json")
CFG = pelitarpc.load_config("pelita.json")
LASNA, BASE = CHAINS["chains"]["lasna"], CHAINS["chains"]["base-sepolia"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cast(*args):
    return subprocess.run([str(BIN / "cast"), *map(str, args)], capture_output=True, text=True, check=True).stdout.strip()


def deployed_code(artifact, name):
    with open(ROOT / "out" / artifact / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)["deployedBytecode"]["object"]


@unittest.skipUnless(ANVIL.exists(), "anvil not installed")
class DeployOnAnvilTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([str(BIN / "forge"), "build", "--quiet"], cwd=ROOT, check=True)
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.procs, cls.rpc = [], {}
        for name, chain in (("lasna", LASNA), ("base-sepolia", BASE)):
            port = free_port()
            cls.procs.append(subprocess.Popen(
                [str(ANVIL), "--port", str(port), "--chain-id", str(chain["chain_id"]), "--silent"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            cls.rpc[name] = f"http://127.0.0.1:{port}"
        for url in cls.rpc.values():
            for _ in range(50):
                try:
                    cast("chain-id", "--rpc-url", url)
                    break
                except subprocess.CalledProcessError:
                    time.sleep(0.1)
        cast("rpc", "anvil_setCode", LASNA["biller"], deployed_code("MockBiller.sol", "MockSystem"),
             "--rpc-url", cls.rpc["lasna"])
        cast("rpc", "anvil_setCode", BASE["biller"], deployed_code("MockBiller.sol", "MockBiller"),
             "--rpc-url", cls.rpc["base-sepolia"])
        (tmp / "ks").mkdir()
        (tmp / "pass").write_text("anvil-only\n")
        out = cast("wallet", "new", tmp / "ks", "--unsafe-password", "anvil-only")
        cls.address = next(w for w in out.split() if w.startswith("0x") and len(w) == 42)
        cls.keystore = next((tmp / "ks").iterdir())
        for url in cls.rpc.values():
            cast("rpc", "anvil_setBalance", cls.address, hex(1000 * 10**18), "--rpc-url", url)
        cls.env = {
            **os.environ,
            "PELITA_KEYSTORE": str(cls.keystore),
            "PELITA_PASSWORD_FILE": str(tmp / "pass"),
            "PELITA_RPC_LASNA": cls.rpc["lasna"],
            "PELITA_RPC_BASE_SEPOLIA": cls.rpc["base-sepolia"],
        }
        cls.out = tmp / "deployments"
        cls.first = cls.deploy()
        cls.second = cls.deploy()

    @classmethod
    def tearDownClass(cls):
        for p in cls.procs:
            p.kill()
            p.wait()
        cls.tmp.cleanup()

    @classmethod
    def deploy(cls):
        p = subprocess.run(["bash", str(ROOT / "scripts" / "deploy.sh"), "--no-verify", "--out", str(cls.out)],
                           env=cls.env, capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            raise AssertionError(f"deploy.sh failed: {p.stderr[-800:]}")
        return p.stdout

    def load(self, name):
        return json.loads((self.out / f"{name}.json").read_text())

    def test_first_run_sends_transactions_second_run_sends_none(self):
        self.assertNotIn("(0 transactions", self.first)
        self.assertIn("deploy: OK (0 transactions sent", self.second)
        self.assertNotIn("\n+ ", "\n" + self.second)

    def test_deployment_files_have_the_shape_the_indexer_reads(self):
        lasna, base = self.load("lasna"), self.load("base-sepolia")
        self.assertEqual(lasna["chain_id"], LASNA["chain_id"])
        self.assertEqual(base["chain_id"], BASE["chain_id"])
        self.assertRegex(lasna["keeper"], r"^0x[0-9a-fA-F]{40}$")
        self.assertRegex(base["tank"], r"^0x[0-9a-fA-F]{40}$")
        self.assertRegex(base["beacon"], r"^0x[0-9a-fA-F]{40}$")
        self.assertGreater(lasna["deploy_block"], 0)
        for dep, name in ((lasna, "Flicker"), (base, "Lantern")):
            self.assertEqual([w["role"] for w in dep["wards"]], ["guarded", "control"])
            self.assertEqual({w["name"] for w in dep["wards"]}, {name})
        loaded = fleet.load_deployments(self.out.parent, ["lasna", "base-sepolia"])
        self.assertEqual(loaded["lasna"]["keeper"], lasna["keeper"])
        self.assertEqual(loaded["base-sepolia"]["tank"], base["tank"])

    def test_keeper_is_wired_guarded_pair_protected_control_not(self):
        lasna, base = self.load("lasna"), self.load("base-sepolia")
        keeper, rpc = lasna["keeper"], self.rpc["lasna"]
        self.assertEqual(cast("call", keeper, "wardCount()(uint256)", "--rpc-url", rpc), "2")
        chain = cast("call", keeper, "chains(uint256)(address,address,uint64,bool)", BASE["chain_id"], "--rpc-url", rpc)
        self.assertIn(base["tank"], chain)
        self.assertIn(str(CFG["destinations"]["base-sepolia"]["callback_gas"]), chain)
        guarded = {w["role"]: w["address"] for w in lasna["wards"]}
        lantern = {w["role"]: w["address"] for w in base["wards"]}
        for role in ("guarded", "control"):
            got = cast("call", guarded[role], "lantern()(address)", "--rpc-url", rpc)
            self.assertEqual(got.lower(), lantern[role].lower())
        ward = deployer.WARD_SIG
        self.assertTrue(deployer.last_bool(cast("call", keeper, ward, LASNA["chain_id"], guarded["guarded"], "--rpc-url", rpc)))
        self.assertFalse(deployer.last_bool(cast("call", keeper, ward, LASNA["chain_id"], guarded["control"], "--rpc-url", rpc)))
        self.assertTrue(deployer.last_bool(cast("call", keeper, ward, BASE["chain_id"], lantern["guarded"], "--rpc-url", rpc)))

    def test_keeper_and_tank_funded_by_plain_transfer_to_config_amounts(self):
        lasna, base = self.load("lasna"), self.load("base-sepolia")
        self.assertEqual(int(cast("balance", lasna["keeper"], "--rpc-url", self.rpc["lasna"])),
                         foundry.to_wei(CFG["funds"]["keeper_fund"]))
        self.assertEqual(int(cast("balance", base["tank"], "--rpc-url", self.rpc["base-sepolia"])),
                         foundry.to_wei(CFG["funds"]["tank_fund"]))
        flicker = lasna["wards"][0]["address"]
        self.assertEqual(int(cast("balance", flicker, "--rpc-url", self.rpc["lasna"])),
                         foundry.to_wei(CFG["demo"]["flicker_fund"]))

    def script(self, name, *args):
        return subprocess.run(["bash", str(ROOT / "scripts" / name), *args], env=self.env,
                              capture_output=True, text=True, timeout=120)

    def test_verify_sh_reads_every_contract_and_prints_its_commands(self):
        p = self.script("verify.sh", str(self.out))
        self.assertEqual(p.returncode, 0, p.stderr[-400:])
        self.assertEqual(p.stdout.count("NO CODE"), 0)
        self.assertIn("$ cast call", p.stdout)
        self.assertIn("--rpc-url $RPC", p.stdout)
        self.assertEqual(p.stdout.count("== "), 7)  # keeper, tank, beacon, 2 flickers, 2 lanterns

    def test_verify_sh_fails_when_a_recorded_contract_has_no_code(self):
        bad = Path(self.tmp.name) / "bad"
        bad.mkdir(exist_ok=True)
        dep = self.load("lasna")
        dep["keeper"] = "0x000000000000000000000000000000000000dEaD"
        dep["wards"] = []
        (bad / "lasna.json").write_text(json.dumps(dep))
        self.assertEqual(self.script("verify.sh", str(bad)).returncode, 1)

    def test_funds_status_reports_keeper_tank_and_wards(self):
        p = self.script("funds.sh", "status", "--json", "--out", str(self.out))
        self.assertEqual(p.returncode, 0, p.stderr[-400:])
        rep = json.loads(p.stdout)
        self.assertEqual(rep["deployer"].lower(), self.address.lower())
        self.assertEqual(rep["chains"]["lasna"]["keeper"]["balance"], CFG["funds"]["keeper_fund"])
        self.assertEqual(rep["chains"]["base-sepolia"]["tank"]["balance"], CFG["funds"]["tank_fund"])
        self.assertEqual(len(rep["chains"]["lasna"]["wards"]), 2)
        self.assertEqual(rep["chains"]["lasna"]["wards"][0]["debt"], "0")

    def test_funds_tukar_refuses_above_limit_and_pays_the_faucet(self):
        over = str(foundry.Decimal(CFG["funds"]["max_swap_eth"]) + 1)
        self.assertEqual(self.script("funds.sh", "tukar", over).returncode, 2)
        faucet, rpc = BASE["lreact_faucet"], self.rpc["base-sepolia"]
        before = int(cast("balance", faucet, "--rpc-url", rpc))
        p = self.script("funds.sh", "tukar", "0.01")
        self.assertEqual(p.returncode, 0, p.stderr[-400:])
        self.assertEqual(int(cast("balance", faucet, "--rpc-url", rpc)) - before, 10**16)
        self.assertEqual(json.loads(p.stdout)["faucet"], faucet)

    def test_rpc_with_wrong_chain_id_is_refused_before_any_transaction(self):
        f = foundry.Foundry(foundry.auth_from_env(self.env), cwd=ROOT)
        rpcs = {"lasna": self.rpc["base-sepolia"], "base-sepolia": self.rpc["base-sepolia"]}
        d = deployer.Deployer(f, CHAINS, CFG, rpcs, Path(self.tmp.name) / "wrong", verify=False, log=lambda *_: None)
        with self.assertRaises(deployer.DeployError):
            d.run()
        self.assertEqual(d.sent, 0)
        self.assertFalse((Path(self.tmp.name) / "wrong").exists())


if __name__ == "__main__":
    unittest.main()
