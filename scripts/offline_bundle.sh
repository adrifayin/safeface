#!/bin/sh
# Build the offline installation bundle on a CONNECTED build machine.
# Output: offline-bundle/ with image tarballs, image digests, model weights
# (if present in models/), SHA256SUMS and the repo itself. Copy the folder to
# the air-gapped server on approved media, then run offline-bundle/install.sh.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/offline-bundle"
rm -rf "$OUT" && mkdir -p "$OUT/images"
cd "$ROOT/infra"
docker compose build
for img in safeface/api:dev safeface/worker:dev safeface/frontend:dev safeface/minio:RELEASE.2024-12-18T13-15-44Z \
           postgres:16.6-bookworm redis:7.4.1-alpine quay.io/keycloak/keycloak:26.0.7 \
           nginxinc/nginx-unprivileged:1.27.3-alpine; do
  docker pull -q "$img" 2>/dev/null || true   # base images; local builds stay local
  file="$OUT/images/$(echo "$img" | tr '/:' '__').tar"
  docker save -o "$file" "$img"
  echo "$img $(docker image inspect --format '{{.Id}}' "$img")" >> "$OUT/image-digests.txt"
done
git -C "$ROOT" archive --format=tar -o "$OUT/safeface-src.tar" HEAD
[ -d "$ROOT/models" ] && tar -C "$ROOT" -cf "$OUT/models.tar" models
cat > "$OUT/install.sh" <<'EOF'
#!/bin/sh
# Run on the air-gapped server from inside the copied offline-bundle folder.
set -eu
sha256sum -c SHA256SUMS
for f in images/*.tar; do docker load -i "$f"; done
mkdir -p safeface && tar -C safeface -xf safeface-src.tar
[ -f models.tar ] && tar -C safeface -xf models.tar
# Record the API image digest for provenance in every finding/report.
echo "SAFEFACE_IMAGE_DIGEST=$(docker image inspect --format '{{.Id}}' safeface/api:dev)" >> safeface/infra/.env.digest
echo "Loaded. Next: cd safeface && python3 scripts/init_secrets.py --host <server-name> && see docs/DEPLOYMENT.md"
EOF
chmod +x "$OUT/install.sh"
(cd "$OUT" && find . -type f ! -name SHA256SUMS ! -name install.sh -print0 | xargs -0 sha256sum > SHA256SUMS)
echo "bundle ready in $OUT"
