# Deployment (air-gapped server)

Reference hardware (TDD §6.4): 1 × NVIDIA GPU 16–24 GB, 16-core CPU, 64 GB RAM,
4 TB encrypted SSD, Linux with Docker + NVIDIA Container Toolkit.

## 1. On the connected build machine

```sh
sh scripts/trivy_scan.sh            # vulnerability scan + SBOMs (security-reports/)
sh scripts/offline_bundle.sh        # images, source, models, SHA256SUMS -> offline-bundle/
```
Fetch model weights first (`scripts/fetch_models.md`) so they are inside the bundle.

## 2. On the air-gapped server

```sh
cd offline-bundle && sh install.sh                      # verifies SHA256SUMS, loads images
cd safeface
python3 scripts/init_secrets.py --host safeface.cyberdome.local --port 443   # production: no --demo
# Install the police-CA certificate as infra/certs/out/server.crt + server.key
cat infra/.env.digest >> infra/.env                     # records the image digest in every finding
# Put pgdata/miniodata/redisdata on the LUKS volume (docs/SECURITY.md §6), set PUBLIC_BIND to the LAN IP
cd infra && docker compose --env-file .env -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Create real users in Keycloak (`https://<host>/auth/admin/`, user `kcadmin`
from `.env`): assign exactly one or more SafeFace realm roles; users configure
TOTP at first login. Then change the Keycloak admin password and restrict
`/auth/admin/` to the IT subnet.

Apply the host egress firewall (docs/SECURITY.md §1) and verify:
`docker compose exec worker-cpu python -c "import socket; socket.create_connection(('1.1.1.1',443),3)"` must fail.

## 3. Daily / periodic operations

| When | What |
|---|---|
| Daily | `docker compose exec api python /app/scripts/export_chain_head.py` (mount `scripts/`), copy output to write-once media |
| Daily | Encrypted backup (below) |
| Weekly | Audit-chain verification from the UI (supervisor/auditor) |
| Quarterly | Restore test into a scratch stack; verify audit chain and a sample of evidence hashes |
| On model change | `fetch_models.md` checklist; two-person enable/disable in the UI |

## 4. Backup and restore (NFR-S8)

```sh
# Backup (age public key of the offline recovery keypair)
docker compose exec -T postgres pg_dump -U postgres -Fc safeface | age -r "$AGE_RECIPIENT" > safeface-$(date +%F).pgdump.age
# MinIO: stop minio briefly (or use a filesystem snapshot) so the copy is consistent
docker compose stop minio && tar -C /srv/safeface -c miniodata | age -r "$AGE_RECIPIENT" > minio-$(date +%F).tar.age \
  && docker compose start minio
```
Object-locked originals keep their retention when restored with the same MinIO
version. Restore: stop the stack, decrypt, `pg_restore -d safeface`, untar the
MinIO volume, start, then **verify the audit chain and re-verify evidence hashes**
before resuming casework; record the restore in the change register.

## 5. Upgrades

New images arrive only via a new offline bundle. Database migrations run in the
one-shot `migrate` service (owner role). Bump `app.__version__` and module
versions on any change that can alter analysis output; old findings keep the
version that produced them, and *Reproduce* refuses if the installed version differs.
