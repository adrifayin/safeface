"""The exported chain verifies with the standalone script, and tampering is caught."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import auth, new_case

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_audit_chain.py"


def run_verifier(path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), str(path), *extra],
                          capture_output=True, text=True, check=False)


def test_export_verifies_independently(client: TestClient, tmp_path: Path) -> None:
    new_case(client)
    r = client.get("/api/v1/audit/export", headers=auth("audrey"))
    assert r.status_code == 200
    export = tmp_path / "audit.jsonl"
    export.write_bytes(r.content)
    ok = run_verifier(export)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    head = ok.stdout.split("head hash ")[1].strip()
    assert run_verifier(export, "--expected-head", head).returncode == 0

    lines = export.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[1])
    row["details"]["injected"] = True
    lines[1] = json.dumps(row)
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bad = run_verifier(tampered)
    assert bad.returncode == 1 and "seq 2" in bad.stdout

    truncated = tmp_path / "truncated.jsonl"
    truncated.write_text("\n".join(export.read_text(encoding="utf-8").splitlines()[:-1]) + "\n")
    assert run_verifier(truncated, "--expected-head", head).returncode == 1
