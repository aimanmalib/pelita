#!/usr/bin/env bash
# Public checks of the deployed site (PRD 4.11 step 4), the way a phone browser sees it through the CDN.
#   scripts/check-public.sh [base-url]     default: https://<DOMAIN from deploy/site.env>/
# Checks: the page is 200 and compressed; HTML keeps `no-transform` and a CSP; the only scripts are our own (app.js and theme-boot.js)
# (nothing injected on the way: no analytics beacon); assets, config, brand and live data answer; the snapshot is
# `no-store` and parses. Exit 0 = all passed.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck disable=SC1091
. "$ROOT/deploy/site.env"
BASE=${1:-https://$DOMAIN/}; BASE=${BASE%/}/
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fail=0
pass() { echo "  ✓ $*"; }; bad() { echo "  ✗ $*"; fail=1; }
get() {  # $1 path, $2 name: headers → $tmp/$2.h, decoded body → $tmp/$2.b; prints the status code
  curl -s -m 20 -A "$UA" -H 'Accept: text/html,application/xhtml+xml,*/*;q=0.8' -H 'Accept-Encoding: gzip, br' \
    --compressed -D "$tmp/$2.h" -o "$tmp/$2.b" -w '%{http_code}' "$BASE$1" || echo 000
}
header() { grep -i "^$2:" "$tmp/$1.h" | tail -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//'; }

c=$(get "" page); [ "$c" = 200 ] && pass "GET / 200" || bad "GET / = $c"
case "$(header page content-type)" in text/html*) pass "HTML served as text/html" ;; *) bad "HTML Content-Type: '$(header page content-type)'" ;; esac
enc=$(header page content-encoding); [ -n "$enc" ] && pass "HTML compressed ($enc)" || bad "HTML not compressed (no content-encoding)"
case "$(header page cache-control)" in *no-transform*) pass "HTML Cache-Control has no-transform" ;; *) bad "HTML Cache-Control: '$(header page cache-control)'" ;; esac
[ -n "$(header page content-security-policy)" ] && pass "CSP present" || bad "no Content-Security-Policy"
foreign=$(grep -oiE '<script[^>]*>' "$tmp/page.b" | grep -viE 'src="js/(app|theme-boot)\.js\?v=[0-9a-f]+"' || true)
[ -z "$foreign" ] && pass "only our own script on the page" || bad "unexpected script tag(s): $foreign"
grep -qiE 'cloudflareinsights|beacon\.min\.js|googletagmanager|google-analytics|plausible' "$tmp/page.b" \
  && bad "analytics text injected into the page" || pass "no analytics injected"

assets=$(grep -oE '(src|href)="[^":#]+"' "$tmp/page.b" | sed -E 's/^(src|href)="//; s/"$//' | sort -u)
unv=$(printf '%s\n' $assets | grep -E '^(css|js|fonts|brand)/' | grep -v '?v=' || true)
[ -z "$unv" ] && pass "every linked asset carries ?v=" || bad "asset(s) without ?v= (a CDN would keep old copies): $unv"
n=0; for a in $assets config/chains.json; do
  c=$(get "$a" asset); n=$((n + 1)); [ "$c" = 200 ] || bad "GET /$a = $c"
  case "$a" in  # a module script or stylesheet with the wrong type is refused by the browser
    *.js\?v=*) case "$(header asset content-type)" in *javascript*) ;; *) bad "/$a Content-Type: '$(header asset content-type)'" ;; esac ;;
    *.css\?v=*) case "$(header asset content-type)" in text/css*) ;; *) bad "/$a Content-Type: '$(header asset content-type)'" ;; esac ;;
  esac
done; pass "$n linked files and config checked"

c=$(get data/snapshot.json snap); [ "$c" = 200 ] && pass "snapshot 200" || bad "snapshot = $c"
case "$(header snap cache-control)" in *no-store*) pass "snapshot no-store" ;; *) bad "snapshot Cache-Control: '$(header snap cache-control)'" ;; esac
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert "generated_at" in d' "$tmp/snap.b" 2>/dev/null \
  && pass "snapshot parses" || bad "snapshot is not valid JSON with generated_at"

[ "$fail" = 0 ] && echo "check-public: OK ($BASE)" || echo "check-public: FAILED ($BASE)"
exit "$fail"
