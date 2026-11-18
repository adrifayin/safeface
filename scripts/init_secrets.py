"""Create deployment secrets and the Keycloak realm import (run once per deployment).

Writes (all git-ignored):
  infra/.env                                   passwords, MinIO KMS key
  infra/keycloak/realm/safeface-realm.json     realm import
  infra/demo-credentials.txt                   demo users' passwords + TOTP secrets (--demo only)

Realm security settings (SRS NFR-S4, TDD §5):
  * TOTP is mandatory: CONFIGURE_TOTP is a default required action for every
    new user, and the browser flow's conditional OTP step then demands it.
  * Brute-force protection: temporary lockout after 5 failed logins.
  * SSO session idle timeout 15 minutes; access tokens live 5 minutes.
  * Public SPA client with PKCE (S256), exact redirect URIs, no implicit or
    password grants. An audience mapper adds "safeface-api" to access tokens.
  * Login and admin events are stored (Keycloak's own audit trail).

Usage:
  python scripts/init_secrets.py --host localhost --port 8443 [--demo]
Re-running refuses to overwrite infra/.env unless --force is given.
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import string
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / "infra"
DEMO_NAMESPACE = uuid.UUID("5afeface-0000-4000-8000-000000000000")
ROLES = ["investigator", "examiner", "supervisor", "admin", "auditor"]
DEMO_USERS = [
    ("ivan.investigator", "Ivan", "Investigator", ["investigator"]),
    ("esha.examiner", "Esha", "Examiner", ["examiner"]),
    ("suku.supervisor", "Suku", "Supervisor", ["supervisor"]),
    ("sara.supervisor", "Sara", "Supervisor", ["supervisor"]),
    ("adam.admin", "Adam", "Admin", ["admin"]),
    ("audrey.auditor", "Audrey", "Auditor", ["auditor"]),
]


def demo_user_id(username: str) -> uuid.UUID:
    """Deterministic Keycloak user id, so scripts/seed_demo.py can set up memberships."""
    return uuid.uuid5(DEMO_NAMESPACE, username)


def token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def password() -> str:
    """Satisfies the realm password policy (length 14+, all character classes)."""
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(16))
    return core + secrets.choice(string.ascii_uppercase) + secrets.choice(string.digits) + "#a"


def otp_secret() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def realm(public: str, demo: dict[str, tuple[str, str]] | None) -> dict[str, object]:
    users = []
    for username, first, last, roles in DEMO_USERS if demo else []:
        pw, otp = demo[username]  # type: ignore[index]
        users.append({
            "id": str(demo_user_id(username)),
            "username": username, "enabled": True, "emailVerified": True,
            "firstName": first, "lastName": last, "email": f"{username}@safeface.invalid",
            "realmRoles": roles + ["default-roles-safeface"], "requiredActions": [],
            "credentials": [
                {"type": "password", "value": pw, "temporary": False},
                {"type": "otp", "userLabel": "demo authenticator",
                 "secretData": json.dumps({"value": otp}),
                 "credentialData": json.dumps({"subType": "totp", "digits": 6, "counter": 0,
                                               "period": 30, "algorithm": "HmacSHA1"})},
            ],
        })
    return {
        "realm": "safeface",
        "enabled": True,
        "displayName": "SafeFace Forensic Workbench",
        "sslRequired": "external",
        "registrationAllowed": False,
        "resetPasswordAllowed": False,
        "rememberMe": False,
        "loginWithEmailAllowed": False,
        "bruteForceProtected": True,
        "failureFactor": 5,
        "permanentLockout": False,
        "waitIncrementSeconds": 900,
        "maxFailureWaitSeconds": 900,
        "maxDeltaTimeSeconds": 43200,
        "quickLoginCheckMilliSeconds": 1000,
        "minimumQuickLoginWaitSeconds": 60,
        "ssoSessionIdleTimeout": 900,
        "ssoSessionMaxLifespan": 36000,
        "accessTokenLifespan": 300,
        "offlineSessionIdleTimeout": 900,
        "revokeRefreshToken": True,
        "refreshTokenMaxReuse": 0,
        "otpPolicyType": "totp",
        "otpPolicyAlgorithm": "HmacSHA1",
        "otpPolicyDigits": 6,
        "otpPolicyPeriod": 30,
        "otpPolicyLookAheadWindow": 1,
        "passwordPolicy": ("length(14) and upperCase(1) and lowerCase(1) and digits(1) and "
                           "specialChars(1) and notUsername and passwordHistory(5)"),
        "eventsEnabled": True,
        "eventsExpiration": 31536000,
        "adminEventsEnabled": True,
        "adminEventsDetailsEnabled": True,
        "internationalizationEnabled": True,
        "supportedLocales": ["en", "ml"],
        "defaultLocale": "en",
        "roles": {"realm": [{"name": r, "description": f"SafeFace {r}"} for r in ROLES]},
        "requiredActions": [
            {"alias": "CONFIGURE_TOTP", "name": "Configure OTP", "providerId": "CONFIGURE_TOTP",
             "enabled": True, "defaultAction": True, "priority": 10, "config": {}},
            {"alias": "UPDATE_PASSWORD", "name": "Update Password", "providerId": "UPDATE_PASSWORD",
             "enabled": True, "defaultAction": False, "priority": 30, "config": {}},
            {"alias": "UPDATE_PROFILE", "name": "Update Profile", "providerId": "UPDATE_PROFILE",
             "enabled": True, "defaultAction": False, "priority": 40, "config": {}},
        ],
        "clients": [{
            "clientId": "safeface-web",
            "name": "SafeFace web client",
            "enabled": True,
            "publicClient": True,
            "protocol": "openid-connect",
            "standardFlowEnabled": True,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "frontchannelLogout": True,
            "redirectUris": [f"{public}/callback"],
            "webOrigins": [public],
            "attributes": {
                "pkce.code.challenge.method": "S256",
                "post.logout.redirect.uris": f"{public}/",
                "use.refresh.tokens": "true",
            },
            "protocolMappers": [{
                "name": "safeface-api-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "consentRequired": False,
                "config": {"included.custom.audience": "safeface-api", "access.token.claim": "true",
                           "id.token.claim": "false", "introspection.token.claim": "true"},
            }],
        }],
        "users": users,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", default="8443")
    ap.add_argument("--demo", action="store_true", help="create demo users (never in production)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    env_path = INFRA / ".env"
    if env_path.exists() and not args.force:
        sys.exit(f"{env_path} exists; use --force to regenerate (this rotates all passwords)")
    public = f"https://{args.host}:{args.port}"

    env = {
        "PUBLIC_HOST": args.host, "PUBLIC_PORT": args.port, "PUBLIC_BIND": "127.0.0.1",
        "POSTGRES_PASSWORD": token(), "SAFEFACE_OWNER_PASSWORD": token(),
        "SAFEFACE_APP_PASSWORD": token(), "KEYCLOAK_DB_PASSWORD": token(),
        "KC_ADMIN_USER": "kcadmin", "KC_ADMIN_PASSWORD": password(), "REDIS_PASSWORD": token(),
        "MINIO_ROOT_USER": "safeface-" + secrets.token_hex(4), "MINIO_ROOT_PASSWORD": token(),
        # MinIO static KMS key (32 random bytes, base64). Production: MinIO KES + KMS/HSM.
        "MINIO_KMS_SECRET_KEY": "safeface-key:" + base64.b64encode(secrets.token_bytes(32)).decode(),
        "OBJECT_LOCK_MODE": "COMPLIANCE", "OBJECT_LOCK_DAYS": "1" if args.demo else "3650",
        "SAFEFACE_ENV": "dev" if args.demo else "prod",
    }
    env_path.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")

    demo = {u[0]: (password(), otp_secret()) for u in DEMO_USERS} if args.demo else None
    realm_dir = INFRA / "keycloak" / "realm"
    realm_dir.mkdir(parents=True, exist_ok=True)
    (realm_dir / "safeface-realm.json").write_text(json.dumps(realm(public, demo), indent=2), encoding="utf-8")
    if demo:
        lines = ["# DEMO ONLY. TOTP secret = raw key bytes (UTF-8) for an authenticator; base32 shown too."]
        for username, (pw, otp) in demo.items():
            b32 = base64.b32encode(otp.encode()).decode().rstrip("=")
            lines.append(f"{username}\tpassword={pw}\ttotp_raw={otp}\ttotp_base32={b32}")
        (INFRA / "demo-credentials.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {env_path}, realm import{', demo credentials' if demo else ''}")


if __name__ == "__main__":
    main()
