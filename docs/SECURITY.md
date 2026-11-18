# Security design and operating procedures

Threat model (TDD §5): sensitive media (NCII, sometimes CSAM), insiders with
legitimate accounts, malicious media files, and a defence lawyer who will
question every step.

## 1. Network isolation (air-gap) — NFR-S1

* Every service except nginx is attached only to the Docker network
  `backend`, declared `internal: true`: Docker gives it **no route outside the
  host**. Workers, API, database, storage and Keycloak cannot reach the internet.
* nginx is also on `edge`, which has IP masquerading disabled, so it can
  accept the published port but cannot originate internet connections.
* The published port binds to `127.0.0.1` by default (`PUBLIC_BIND` in `.env`);
  set it to the server's police-LAN address in production.
* **Host egress firewall (required, defence in depth).** On the server:

  ```sh
  # nftables: allow only established traffic and the police LAN; drop everything else outbound
  nft add table inet safeface
  nft add chain inet safeface out '{ type filter hook output priority 0; policy drop; }'
  nft add rule inet safeface out ct state established,related accept
  nft add rule inet safeface out oifname "lo" accept
  nft add rule inet safeface out ip daddr 10.0.0.0/8 accept      # police LAN (adjust)
  nft add chain inet safeface fwd '{ type filter hook forward priority 0; policy drop; }'
  nft add rule inet safeface fwd ct state established,related accept
  nft add rule inet safeface fwd iifname "br-*" oifname "br-*" accept   # container <-> container
  ```
  Also set `"iptables": true` (default) in `/etc/docker/daemon.json` and do not
  give the server a default route to the internet.
* Verified by test `test_container_has_no_internet_route` (runs inside the
  isolated test network) and `test_no_external_urls_or_download_calls_in_app_code`.
* No telemetry: Swagger/ReDoc (CDN-loaded) are disabled; the frontend bundles
  every asset; the CSP is `default-src 'self'` with `connect-src 'self'`;
  WeasyPrint's URL fetcher refuses everything except inline `data:` URIs;
  MinIO update/call-home are off; libraries with online checks are pinned to
  versions without them and guarded by env vars (`NO_ALBUMENTATIONS_UPDATE`,
  `HF_HUB_OFFLINE`).

## 2. Identity and access — NFR-S3, NFR-S4, FR-6.1

* Keycloak realm (`scripts/init_secrets.py`): TOTP mandatory (default required
  action), lockout after 5 failures (15 min), SSO idle timeout 15 min, 5-minute
  access tokens, refresh-token rotation, PKCE S256, exact redirect URIs, no
  password or implicit grants, login + admin events stored.
* The SPA keeps tokens in memory only and signs out after 15 minutes idle.
* The API verifies RS256 signature, issuer, audience (`safeface-api`) and
  expiry on every request (`app/core/security.py`). Optional:
  `SAFEFACE_REQUIRE_AMR_OTP=true` rejects tokens without `otp` in `amr` once
  the Keycloak AMR mapper is configured.
* Authorisation is one table (`app/core/policy.py`): role **and** case
  membership on every case-scoped route; non-members get 404. Administrators
  have no case-scoped action at all, so they can never see media. Auditors see
  case metadata, reports and the audit log, never media.
* Separation of duties: a conclusion cannot be approved by its author
  (API **and** database trigger); model enable/disable needs an admin request
  and a different supervisor's approval.
* Restrict the Keycloak admin console (`/auth/admin/`) to the IT subnet in
  nginx (`allow`/`deny`) for production.

## 3. Evidence integrity — NFR-R3, FR-1.3, FR-1.6

* Upload is streamed; SHA-256 and MD5 are computed over exactly the bytes
  stored. The stored object is then read back and re-hashed.
* `evidence-originals` has MinIO object lock (COMPLIANCE, retention from
  `OBJECT_LOCK_DAYS`; 3650 days by default in production) — not even the MinIO
  root user can overwrite or delete an original during retention.
* Analysis uses working copies; the worker re-hashes each copy against the
  ingest hash before every analysis and refuses on mismatch.
* Every report generation re-hashes every original and working copy and
  refuses (and audits the refusal) if any hash differs.
* Database: the runtime role has only SELECT/INSERT on evidence, verification,
  finding, note, report and audit tables; triggers refuse UPDATE/DELETE/TRUNCATE
  for every role including the owner.

### 3a. Short retention of derived files (7 minutes)

Agreed with the user to minimise how long sensitive media copies exist:

| Data | Kept | Where |
|---|---|---|
| Sealed original (write-once), SHA-256/MD5, hash re-verifications | Permanently (object-lock retention) | MinIO `evidence-originals`, PostgreSQL |
| Findings: scores, summaries, provenance, artefact SHA-256s | Permanently | PostgreSQL |
| Audit chain, reports (PDF + SHA-256) | Permanently | PostgreSQL, MinIO `reports` |
| Working copies, figures/heatmaps/plots | **Deleted 7 minutes after the last analysis** of the item (`SAFEFACE_WORK_RETENTION_SECONDS`, default 420) | MinIO `working`, `artefacts` |
| Frames/audio extracted during analysis | Deleted when the job ends | worker tmpfs |
| The browser's copy of an image/video/figure | In memory only (no cache), **wiped 7 minutes after opening** or on leaving the page | browser |

A purged working copy is re-created from the sealed original, and its SHA-256 is checked, whenever it is
needed again (viewing or re-analysis). Purges (`evidence.work_files_purged`), restores
(`evidence.working_copy_restored`) and browser wipes (`evidence.browser_copy_wiped`) are written to the audit
chain. A report generated after a purge lists each deleted figure with its recorded SHA-256; re-run the analysis
first to include the figures. The application can never delete an original (enforced in code and by object lock).

## 4. Audit log — NFR-S5, FR-6.2

* `entry_hash = SHA-256(prev_hash || canonical_json(entry))`, serialised by
  an advisory lock and written in the same transaction as the change.
* Logged: login/logout (SPA session start), every view of evidence, findings,
  artefacts and custody, uploads, analyses (queued/started/completed/failed),
  notes, conclusions, approvals, report generation/preview/export, s.63 views,
  registry changes, audit verification and export.
* Verification: `GET /audit/verify` (UI button) and the standalone
  `scripts/verify_audit_chain.py` over the JSONL export.
* **Daily:** run `scripts/export_chain_head.py` (cron) and copy the printed
  head to a second write-once medium. Truncation of recent entries is only
  detectable against a previously exported head.

## 5. Sandboxed processing of untrusted media — NFR-S7

* File type decided by magic bytes, before storage; > 4 GiB rejected while
  streaming; decompression bombs > 200 MP refused by Pillow.
* Workers: non-root (uid 10001), read-only root filesystem, all capabilities
  dropped, `no-new-privileges`, private tmpfs `/work` and `/tmp`, memory/CPU/PID
  limits, Celery soft/hard time limits (840/900 s), no internet route.
  External tools (ExifTool, c2patool) run with a minimal environment and a
  timeout. Recommended for production: Docker's default seccomp profile is in
  effect; add an AppArmor profile (`security_opt: apparmor=safeface-worker`).
* Model weights: SHA-256 verified on every load; unlisted or unverified files
  refused; `torch.load(weights_only=True)` so a checkpoint cannot execute code.

## 6. Data at rest and in transit — NFR-S2, NFR-S8

* MinIO server-side encryption (SSE-S3, AES-256-GCM) on every bucket, using
  the KMS key in `.env` (`MINIO_KMS_SECRET_KEY`). **Production:** replace the
  static key with MinIO KES backed by the police KMS/HSM; keep the key off the
  data volume.
* PostgreSQL data must live on an encrypted volume. Example (LUKS):

  ```sh
  cryptsetup luksFormat /dev/nvme1n1 && cryptsetup open /dev/nvme1n1 sfdata
  mkfs.ext4 /dev/mapper/sfdata && mount /dev/mapper/sfdata /srv/safeface
  # in docker-compose.yml: replace the named volumes with /srv/safeface/{pgdata,miniodata,redisdata}
  ```
  Unlock at boot with a TPM-bound key or an operator passphrase.
* TLS 1.3 only at nginx, internal CA (`infra/certs/gen_dev_certs.py` for dev;
  police CA in production). Internal hops are on the isolated Docker network;
  for TLS on every hop, enable Postgres `ssl=on`, MinIO `--certs-dir`, Redis
  `tls-port` with certificates from the same CA (planned hardening).
* Backups: `pg_dump` + `mc mirror` of all buckets, encrypted with `age` or
  GPG to an offline key; restore procedure in `docs/DEPLOYMENT.md`. Test a
  restore quarterly and verify the audit chain after restore.

## 7. Supply chain

* All Python packages pinned in `backend/requirements*.txt` plus a full
  transitive lock (`backend/constraints.txt`); npm packages pinned and locked
  (`package-lock.json`, installed with `--ignore-scripts`); base images pinned
  by tag (record digests in `offline-bundle/image-digests.txt`).
* `scripts/trivy_scan.sh` scans every image and writes a CycloneDX SBOM per
  image (run on the build machine, never on the air-gapped server).
* c2patool binary verified against the GitHub-published SHA-256 at build time.
* MinIO is built from a pinned upstream source tag (MinIO no longer publishes
  community images).

## 8. Examiner wellbeing — NFR-U1

Evidence and figures are blurred until the examiner clicks *Reveal*;
greyscale toggle available. CSAM must be handled only under documented legal
authority and is never used for testing or training (NFR-L3).
