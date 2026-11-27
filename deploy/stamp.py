#!/usr/bin/env python3
"""Prepare a clean build context for the site image (called by deploy/deploy.sh).

1. Version the assets: web/index.html loads css/, js/, fonts/, img/ and brand/ with ?v=<version> (CSS url() too), and every relative import between the
   ES modules carries the same ?v=. All of them, or none: a module loaded under two URLs runs twice (two copies of
   the language state). Cloudflare keeps .css/.js for hours whatever the origin says, so a new URL is the only
   reliable way to ship a change.
   @SITE@ in index.html (canonical, og:url, og:image: link previews need absolute URLs) becomes https://<DOMAIN>
   from deploy/site.env, and @V@ the version (the preview card is cached by URL like the rest).
2. Render deploy/nginx.conf + deploy/nginx.headers into deploy/rendered/, with the Content-Security-Policy
   connect-src taken from the RPCs of the active chains in config/chains.json (the fuel gauge calls the RPC
   from the browser).

    python3 deploy/stamp.py <build-context-dir> <version>
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

PAGE_ASSET = re.compile(r'((?:src|href)=")((?:css|js|fonts|brand|img)/[^"?#]+\.(?:css|js|woff2|png|svg|webp))(")')
CSS_URL = re.compile(r'(url\(\s*)(["\']?)(\.\./[^"\')?#]+)\2(\s*\))')
MODULE_SPEC = re.compile(r'((?:\bfrom|\bimport)\s*\(?\s*)(["\'])(\.{1,2}/[^"\'?#]+\.js)\2')
ANY_RELATIVE_JS = re.compile(r'(["\'])(\.{1,2}/[^"\']+\.js[^"\']*)\1')


def stamp_page(html, version):
    return PAGE_ASSET.sub(lambda m: f"{m[1]}{m[2]}?v={version}{m[3]}", html)


def stamp_module(source, version):
    return MODULE_SPEC.sub(lambda m: f"{m[1]}{m[2]}{m[3]}?v={version}{m[2]}", source)


def stamp_css(source, version):
    return CSS_URL.sub(lambda m: f"{m[1]}{m[2]}{m[3]}?v={version}{m[2]}{m[4]}", source)


def unversioned(text, version):
    """Relative .js specifiers left without the expected ?v= (must be empty after stamping)."""
    return [m[2] for m in ANY_RELATIVE_JS.finditer(text) if not m[2].endswith(f"?v={version}")]


def site_origin(site_env):
    m = re.search(r"^DOMAIN=([a-z0-9.-]+)$", site_env, re.M)
    if not m:
        raise ValueError("DOMAIN missing from deploy/site.env")
    return f"https://{m[1]}"


def fill_site(html, origin, version):
    out = html.replace("@SITE@", origin).replace("@V@", version)
    if re.search(r"@(SITE|V)@", out):
        raise ValueError("unfilled @SITE@ or @V@")
    return out


def connect_origins(chains):
    origins = []
    for chain in chains["chains"].values():
        if chain.get("aktif", chain.get("active")) and chain.get("rpc"):
            u = urlsplit(chain["rpc"])
            if u.scheme != "https" or not u.netloc:
                raise ValueError(f"RPC must be https: {chain['rpc']}")
            origin = f"https://{u.netloc}"
            if origin not in origins:
                origins.append(origin)
    if not origins:
        raise ValueError("no active chain with an RPC")
    return origins


def render(template, origins):
    out = template.replace("@CONNECT_SRC@", " ".join(origins))
    if "@" in out.replace("@sha256", ""):
        raise ValueError("unfilled placeholder left in nginx template")
    return out


def main(argv):
    if len(argv) != 3 or not re.fullmatch(r"[0-9a-f]{7,40}", argv[2]):
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    ctx, version = Path(argv[1]), argv[2]
    web = ctx / "web"
    index = web / "index.html"
    origin = site_origin((ctx / "deploy" / "site.env").read_text(encoding="utf-8"))
    index.write_text(fill_site(stamp_page(index.read_text(encoding="utf-8"), version), origin, version), encoding="utf-8")
    missing = []
    for js in sorted((web / "js").glob("*.js")):
        text = stamp_module(js.read_text(encoding="utf-8"), version)
        js.write_text(text, encoding="utf-8")
        missing += [f"{js.name}: {s}" for s in unversioned(text, version)]
    for css in sorted((web / "css").glob("*.css")):
        text = stamp_css(css.read_text(encoding="utf-8"), version)
        css.write_text(text, encoding="utf-8")
        if CSS_URL.search(text):
            missing.append(f"{css.name}: url() without ?v=")
    if PAGE_ASSET.search(index.read_text(encoding="utf-8")):
        missing.append("index.html: an asset without ?v=")
    if missing:
        print("stamp: unversioned imports:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    origins = connect_origins(json.loads((ctx / "config" / "chains.json").read_text(encoding="utf-8")))
    out = ctx / "deploy" / "rendered"
    out.mkdir(parents=True, exist_ok=True)
    (out / "pelita.conf").write_text(render((ctx / "deploy" / "nginx.conf").read_text(encoding="utf-8"), origins), encoding="utf-8")
    (out / "pelita.headers").write_text(render((ctx / "deploy" / "nginx.headers").read_text(encoding="utf-8"), origins), encoding="utf-8")
    print(f"stamp: v={version}, connect-src {' '.join(origins)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
