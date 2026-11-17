"""Offline checks of the site deploy (deploy/): asset versioning, rendered nginx config, build context, uptime watch."""

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ops"))
import uptime  # noqa: E402

spec = importlib.util.spec_from_file_location("stamp", ROOT / "deploy" / "stamp.py")
stamp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stamp)
V = "0123456789ab"


class StampTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ctx)
        for part in ("web", "config", "deploy"):
            shutil.copytree(ROOT / part, self.ctx / part)

    def test_every_asset_and_module_import_gets_the_same_version(self):
        self.assertEqual(stamp.main(["stamp", str(self.ctx), V]), 0)
        html = (self.ctx / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f'src="js/app.js?v={V}"', html)
        self.assertIn(f'href="css/site.css?v={V}"', html)
        for js in (self.ctx / "web" / "js").glob("*.js"):
            text = js.read_text(encoding="utf-8")
            specs = re.findall(r'["\'](\.{1,2}/[^"\']+\.js[^"\']*)["\']', text)
            self.assertTrue(all(s.endswith(f"?v={V}") for s in specs), (js.name, specs))
        self.assertGreater(len(list((self.ctx / "web" / "js").glob("*.js"))), 1)

    def test_an_import_form_it_cannot_version_stops_the_deploy(self):
        js = self.ctx / "web" / "js" / "app.js"
        js.write_text(js.read_text(encoding="utf-8") + '\nconst x = "./later.js";\n', encoding="utf-8")
        self.assertEqual(stamp.main(["stamp", str(self.ctx), V]), 1)

    def test_dynamic_and_single_quoted_imports_are_versioned(self):
        out = stamp.stamp_module("import('./a.js'); import { b } from './b.js';", V)
        self.assertEqual(stamp.unversioned(out, V), [])

    def test_rendered_nginx_allows_only_active_rpcs_and_has_no_placeholder(self):
        self.assertEqual(stamp.main(["stamp", str(self.ctx), V]), 0)
        chains = json.loads((ROOT / "config" / "chains.json").read_text(encoding="utf-8"))["chains"]
        headers = (self.ctx / "deploy" / "rendered" / "pelita.headers").read_text(encoding="utf-8")
        for c in chains.values():
            host = re.sub(r"^https://([^/]+).*$", r"\1", c["rpc"])
            (self.assertIn if c.get("aktif") else self.assertNotIn)(host, headers)
        for f in (self.ctx / "deploy" / "rendered").iterdir():
            self.assertNotIn("@CONNECT_SRC@", f.read_text(encoding="utf-8"))

    def test_plain_http_rpc_is_refused(self):
        with self.assertRaises(ValueError):
            stamp.connect_origins({"chains": {"x": {"aktif": True, "rpc": "http://rpc.example"}}})

    def test_bad_version_is_refused(self):
        self.assertEqual(stamp.main(["stamp", str(self.ctx), "../x"]), 2)


class NginxAndContextTest(unittest.TestCase):
    def test_every_location_with_headers_includes_the_security_headers(self):
        conf = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        for block in re.findall(r"location[^{]*\{[^}]*\}", conf):
            if "add_header" in block:
                self.assertIn("include /etc/nginx/conf.d/pelita.headers;", block, block)

    def test_snapshot_is_no_store_and_html_no_transform(self):
        conf = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        # ^~: without it the `\.json$` regex location wins and /data/snapshot.json is a 404 (first deploy, 17 Nov).
        data = re.search(r"location \^~ /data/ \{[^}]*\}", conf).group(0)
        self.assertIn('"no-store"', data)
        self.assertEqual(conf.count("no-cache, no-transform"), 2)

    def test_build_context_leaves_out_state_internal_notes_and_env(self):
        lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        rules = [r.strip() for r in lines if r.strip() and not r.startswith("#")]
        self.assertEqual(rules[0], "*")
        for r in ("state/", "dalaman/", ".env*"):
            self.assertIn(r, rules)
        self.assertGreater(rules.index("state/"), max(i for i, r in enumerate(rules) if r.startswith("!")))

    def test_container_names_carry_the_project_prefix(self):
        env = uptime.site_env(ROOT / "deploy" / "site.env")
        for k in ("CONTAINER", "HOLDER", "IMAGE"):
            self.assertTrue(env[k].startswith("pelita-"), k)
        self.assertRegex(env["BASE_IMAGE"], r"@sha256:[0-9a-f]{64}$")


class UptimeTest(unittest.TestCase):
    def test_warns_once_after_n_failures_and_once_on_recovery(self):
        state, sent = {}, []
        for code in (0, 502, 0, 0, 0, 200, 200):
            state, kind = uptime.step(state, code, 3)
            sent.append(kind)
        self.assertEqual(sent, [None, None, "site_down", None, None, "site_up", None])

    def test_run_formats_the_text_from_config_and_keeps_state(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for part in ("deploy/site.env", "config/pelita.json", "config/chains.json"):
            (root / part).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / part, root / part)
        calls = []
        for _ in range(3):
            uptime.run(root, get=lambda url, ua: 0, notify=lambda t, lvl: calls.append((t, lvl)) or 0, now=lambda: 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "warn")
        self.assertIn("https://pelita.sasateguh.com/", calls[0][0])
        self.assertNotIn("{", calls[0][0])
        uptime.run(root, get=lambda url, ua: 200, notify=lambda t, lvl: calls.append((t, lvl)) or 0, now=lambda: 2)
        self.assertEqual([c[1] for c in calls], ["warn", "info"])

    def test_undelivered_warning_is_tried_again(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for part in ("deploy/site.env", "config/pelita.json", "config/chains.json"):
            (root / part).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / part, root / part)
        calls = []
        for rc in (1, 1, 1, 0, 0):
            uptime.run(root, get=lambda url, ua: 0, notify=lambda t, lvl, rc=rc: calls.append(lvl) or rc, now=lambda: 1)
        self.assertEqual(calls, ["warn", "warn"])


if __name__ == "__main__":
    unittest.main()
