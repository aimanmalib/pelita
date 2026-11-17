# ADR 0007: Site deploy (one nginx container behind the host proxy)

Status: accepted, 17 Nov 2026

## Context

PRD §4.11 asks for a small static container (`nginx:alpine`) serving `web/`, with `state/public/` mounted read-only at
`/data`, 0.5 CPU, an image built through the host's image builder, an https route with compression, `deploy/deploy.sh
[--status|--rollback]` with a held rollback image, a 5-minute uptime watch, and public checks that see the site the way a
phone sees it through Cloudflare (HTML `no-transform`, nothing injected, compressed, `snapshot.json` `no-store`).

## Decision

- **Image** (`deploy/Dockerfile`): nginx stable-alpine pinned by digest in `deploy/site.env`; `web/` at `/`, `brand/` at
  `/brand/`, `config/chains.json` at `/config/chains.json` (one source for chain data, ADR 0006). Built from a clean
  `git archive HEAD`; `.dockerignore` is an allow-list and repeats `state/`, `dalaman/`, `.env*`.
- **Host values**: the proxy network, proxy container, route directory and certificate resolver describe the host, not the
  project, so they live outside the repository (`~/.config/pelita/host.env`, keys in `deploy/host.env.example`);
  `deploy.sh` stops with a clear message when one is missing.
- **Container**: `pelita-web` on the shared proxy network, read-only root, tmpfs for nginx scratch, all capabilities dropped
  except the three nginx needs to drop to its worker user, 0.5 CPU, 64 MB, health check on `/healthz`. The live snapshot is a
  read-only directory mount (`state/public` → `/data`): the indexer replaces the file atomically, which a single-file mount
  would not see.
- **Asset versions** (`deploy/stamp.py`): Cloudflare keeps `.css`/`.js` (and fonts, images) for hours whatever the origin
  says, so every local asset URL gets `?v=<hash>`, where the hash covers every served path (`web`, `brand`,
  `config/chains.json`, `deploy`). Measured on the first deploy: with `?v=` taken from `web/` alone, a fix to response headers
  kept the old cached copies. All ES module imports carry the same `?v=` (a module under two URLs runs twice); `stamp.py`
  refuses to build when one is left unversioned.
- **Headers** (`deploy/nginx.conf` + `deploy/nginx.headers`, one include per location because `add_header` in a location
  drops inherited ones): CSP with `script-src 'self'` and `connect-src` = origins of the active chains' RPCs, rendered from
  `config/chains.json`; `style-src` also allows inline styles because WebKit refuses its own form-control styles otherwise
  (three console errors per page on iPhone 13, measured). HTML `no-cache, no-transform`; `/data/` `no-store` (prefix `^~`,
  or the `.json` rule takes it); JSON settings `no-cache`; versioned assets cached.
- **Route**: traefik file route (`deploy/traefik.yaml.tmpl`) with `compress` (floor 256 bytes) and http → https.
- **Tags** live in `state/deploy/` (not tracked). `--status` reports whether the served files match HEAD by comparing the
  tree of the served paths, so a docs-only commit after a deploy does not read as "out of date".
- **Uptime** (`ops/uptime.py`, cron `PELITA-UPTIME` every 5 min, wrapped in `jalan-jadual.sh` + `flock`): one GET per run;
  `UPTIME_FAILS_BEFORE_WARN` failures in a row → one warning, first success after → one info line. Texts in
  `config/pelita.json` `alerts.text`. A notify that did not deliver is retried next run.
- **Public checks** (`scripts/check-public.sh`): Safari UA; page 200, `text/html`, compressed, `no-transform`, CSP; only our
  own script tag and no analytics text; every linked asset versioned, 200 and the right type; config and snapshot answer.

## Consequences

- Rollback: `deploy/deploy.sh --rollback` runs the image kept by the stopped `pelita-web-undur` container; running it twice
  returns to the current image (tested 17 Nov).
- Removing the site: delete the route file in the proxy and the two containers. Nothing else on the host depends on it.
- A new served path (e.g. an OG image) must be added to `SERVED` in `deploy/deploy.sh` and to `.dockerignore`, or it is
  neither in the image nor in the version hash.
