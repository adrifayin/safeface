#!/bin/sh
# Scan every SafeFace image for known vulnerabilities and write an SBOM per image.
# Run on the connected BUILD machine (Trivy downloads its vulnerability DB);
# never on the air-gapped server. Fails (exit 1) on HIGH/CRITICAL findings
# that have a fix available.
#
#   sh scripts/trivy_scan.sh            # uses aquasec/trivy in Docker
set -eu
TRIVY_IMAGE="aquasec/trivy:0.58.1"
OUT="${OUT:-security-reports}"
mkdir -p "$OUT"
IMAGES="safeface/api:dev safeface/worker:dev safeface/frontend:dev safeface/minio:RELEASE.2024-12-18T13-15-44Z
postgres:16.6-bookworm redis:7.4.1-alpine quay.io/keycloak/keycloak:26.0.7 nginxinc/nginx-unprivileged:1.27.3-alpine"

status=0
for img in $IMAGES; do
  name=$(echo "$img" | tr '/:' '__')
  echo "== $img"
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD/$OUT:/out" "$TRIVY_IMAGE" \
    image --quiet --format cyclonedx --output "/out/$name.sbom.json" "$img"
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD/$OUT:/out" "$TRIVY_IMAGE" \
    image --quiet --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 \
    --format table --output "/out/$name.vulns.txt" "$img" || { echo "   HIGH/CRITICAL findings: see $OUT/$name.vulns.txt"; status=1; }
done
exit $status
