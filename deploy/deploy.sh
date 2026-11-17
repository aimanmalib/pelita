#!/usr/bin/env bash
# Deploy the Pelita site (PRD 4.11): one nginx container behind the host's reverse proxy.
#   deploy/deploy.sh             build HEAD from a clean `git archive`, run it, install the route, verify
#   deploy/deploy.sh --rollback  run the previous image again (kept by the stopped holder container)
#   deploy/deploy.sh --status    container, deployed commit, whether the served files match HEAD, public code
# Values: deploy/site.env. Deploy tags: state/deploy/ (not tracked). Live data: state/public/ mounted at /data.
set -euo pipefail
DEPLOY=$(cd "$(dirname "$0")" && pwd); ROOT=$(dirname "$DEPLOY")
# shellcheck disable=SC1091
. "$DEPLOY/site.env"
TAGS="$ROOT/state/deploy"; mkdir -p "$TAGS" "$ROOT/state/public"
URL="https://$DOMAIN/"
SERVED="web brand config/chains.json deploy"   # paths that end up in the image
ok() { echo "  ✓ $*"; }; die() { echo "  ✗ $*" >&2; exit 1; }

public_code() { curl -s -o /dev/null -w '%{http_code}' -m 20 "$URL" || true; }
tag_commit() { echo "${1%%-*}"; }
served_tree() { git -C "$ROOT" ls-tree "$1" -- $SERVED | git hash-object --stdin; }

status() {
  docker ps -a --filter "name=^${CONTAINER}" --format '  {{.Names}}  {{.Image}}  {{.Status}}'
  local cur; cur=$(cat "$TAGS/CURRENT_TAG" 2>/dev/null || echo -)
  echo "  current $cur · previous $(cat "$TAGS/PREVIOUS_TAG" 2>/dev/null || echo -)"
  if [ "$cur" != - ] && git -C "$ROOT" cat-file -e "$(tag_commit "$cur")^{commit}" 2>/dev/null; then
    if [ "$(served_tree "$(tag_commit "$cur")")" = "$(served_tree HEAD)" ]; then echo "  served files = HEAD ($(git -C "$ROOT" rev-parse --short HEAD))"
    else echo "  served files differ from HEAD: deploy again"; fi
  fi
  echo "  route: $(docker exec "$PROXY_CONTAINER" test -f "$PROXY_DYNAMIC_DIR/pelita.yaml" && echo present || echo MISSING)"
  echo "  public GET / $(public_code)"
}

hold_previous() {  # $1 = image ID the replaced container ran
  local prev id=${1:-}
  prev=$(cat "$TAGS/PREVIOUS_TAG" 2>/dev/null) || { echo "  note: first deploy, no rollback image yet"; return 0; }
  [ -n "$id" ] || id=$(docker image inspect -f '{{.Id}}' "$IMAGE:$prev" 2>/dev/null) || id=""
  [ -n "$id" ] || { echo "  WARNING: rollback image $IMAGE:$prev not found" >&2; return 1; }
  docker rm -f "$HOLDER" >/dev/null 2>&1 || true
  docker tag "$id" "$IMAGE:$prev"
  docker create --name "$HOLDER" --network none --restart no --label "pelita.tag=$prev" "$IMAGE:$prev" >/dev/null
  ok "rollback image held: $IMAGE:$prev"
}

case "${1:-}" in
  --status) status; exit 0 ;;
  --rollback)
    TAG=$(cat "$TAGS/PREVIOUS_TAG" 2>/dev/null) || die "no previous tag"
    if ! docker image inspect "$IMAGE:$TAG" >/dev/null 2>&1; then
      id=$(docker inspect -f '{{.Image}}' "$HOLDER" 2>/dev/null) || die "image $IMAGE:$TAG is gone"
      docker tag "$id" "$IMAGE:$TAG"
    fi
    cp "$TAGS/CURRENT_TAG" "$TAGS/PREVIOUS_TAG" ;;
  "")
    [ -n "$(dig +short "$DOMAIN" @1.1.1.1)" ] || die "$DOMAIN does not resolve: certificate would fail, nothing changed"
    [ -z "$(git -C "$ROOT" status --porcelain)" ] || die "working tree not clean: commit first (the image is built from HEAD)"
    [ "$(df -BG --output=avail / | tail -1 | tr -dc 0-9)" -ge "$MIN_FREE_GB" ] || die "less than $MIN_FREE_GB GB free on /"
    TAG=$(git -C "$ROOT" rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M)
    ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
    git -C "$ROOT" archive HEAD | tar -x -C "$ctx"   # untracked and ignored files never reach the image
    python3 "$DEPLOY/stamp.py" "$ctx" "$(git -C "$ROOT" rev-parse --short=12 HEAD:web)" || die "stamp failed"
    "$HOME/bin/bina-imej.sh" -q --build-arg BASE_IMAGE="$BASE_IMAGE" -f "$ctx/deploy/Dockerfile" -t "$IMAGE:$TAG" "$ctx" >/dev/null \
      || die "image build failed"
    ok "image $IMAGE:$TAG built"
    [ -r "$TAGS/CURRENT_TAG" ] && cp "$TAGS/CURRENT_TAG" "$TAGS/PREVIOUS_TAG" ;;
  *) echo "usage: deploy.sh [--rollback|--status]"; exit 2 ;;
esac

old_id=$(docker inspect -f '{{.Image}}' "$CONTAINER" 2>/dev/null || true)
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" --network "$NETWORK" --restart unless-stopped \
  --cpus "$CPUS" --memory "$MEMORY" --read-only --tmpfs /var/cache/nginx --tmpfs /var/run --tmpfs /tmp \
  --security-opt no-new-privileges:true --cap-drop ALL --cap-add CHOWN --cap-add SETUID --cap-add SETGID \
  -v "$ROOT/state/public:/data:ro" --label traefik.enable=false \
  --log-opt max-size=5m --log-opt max-file=2 "$IMAGE:$TAG" >/dev/null
echo "$TAG" > "$TAGS/CURRENT_TAG"
for _ in $(seq 20); do [ "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER")" = healthy ] && break; sleep 3; done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER")" = healthy ] && ok "container healthy" || die "container not healthy: deploy/deploy.sh --rollback"

route=$(mktemp)
sed -e "s|@DOMAIN@|$DOMAIN|g" -e "s|@CERT_RESOLVER@|$CERT_RESOLVER|g" -e "s|@CONTAINER@|$CONTAINER|g" "$DEPLOY/traefik.yaml.tmpl" > "$route"
grep -q '@[A-Z_]*@' "$route" && { rm -f "$route"; die "route template not filled"; }
docker cp "$route" "$PROXY_CONTAINER:$PROXY_DYNAMIC_DIR/pelita.yaml"; rm -f "$route"
ok "route installed"
no_rollback=0; hold_previous "$old_id" || no_rollback=1

# Keep only the current and previous images: the host disk is shared.
docker images "$IMAGE" --format '{{.Tag}}' | grep -vxF -e "$TAG" -e "$(cat "$TAGS/PREVIOUS_TAG" 2>/dev/null || echo -)" \
  | sed "s|^|$IMAGE:|" | xargs -r docker rmi >/dev/null 2>&1 || true

# A new route or certificate takes a while: wait and retry before calling it a failure.
code=000
for _ in $(seq 9); do code=$(public_code); [ "$code" = 200 ] && break; sleep 10; done
echo "  tag $TAG · public GET / $code"
[ "$code" = 200 ] || die "public GET / is not 200 yet: check certificate and route; undo with deploy/deploy.sh --rollback"
bash "$ROOT/scripts/check-public.sh" || die "public checks failed (scripts/check-public.sh)"
[ "$no_rollback" = 0 ] || die "live, but no rollback image is held (warning above)"
echo "SIAP: $URL"
