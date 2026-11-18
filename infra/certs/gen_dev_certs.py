"""Generate a development internal CA and a TLS server certificate for nginx.

Output (git-ignored): infra/certs/out/{ca.crt, ca.key, server.crt, server.key}
Import ca.crt into the workstation browser's trust store for the dev host.
PRODUCTION: use the police internal CA instead; never reuse these files.

Runs with the ``cryptography`` package already in the backend image:
  docker run --rm -v "$PWD/infra/certs:/certs" -w /certs safeface/api:dev \
      python gen_dev_certs.py --host localhost
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _write_key(key: ec.EllipticCurvePrivateKey, path: Path) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", action="append", default=[], help="DNS name or IP (repeatable)")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    hosts = args.host or ["localhost"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SafeFace DEV"),
                         x509.NameAttribute(NameOID.COMMON_NAME, "SafeFace DEV internal CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=825))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                       content_commitment=False, key_encipherment=False,
                                       data_encipherment=False, key_agreement=False,
                                       encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))

    sans: list[x509.GeneralName] = []
    for h in hosts + ["127.0.0.1"]:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            sans.append(x509.DNSName(h))
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=397))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))

    (out / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    _write_key(ca_key, out / "ca.key")
    (out / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                                     + ca.public_bytes(serialization.Encoding.PEM))
    _write_key(key, out / "server.key")
    (out / "server.key").chmod(0o644)  # nginx (uid 101) must read it inside the container
    print(f"wrote CA and server certificate for {', '.join(hosts)} to {out}/")


if __name__ == "__main__":
    main()
