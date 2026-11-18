"""Air-gap checks: no outbound network, no CDN assets, no runtime downloads."""

from __future__ import annotations

import os
import re
import socket
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"


@pytest.mark.skipif(os.environ.get("SAFEFACE_EXPECT_NO_NETWORK") != "1",
                    reason="only meaningful inside the isolated test network")
@pytest.mark.parametrize("host", ["1.1.1.1", "8.8.8.8"])
def test_container_has_no_internet_route(host: str) -> None:
    with pytest.raises(OSError), socket.create_connection((host, 443), timeout=3):
        pass


def test_no_external_urls_or_download_calls_in_app_code() -> None:
    """Application code must not reference internet hosts or download helpers."""
    allowed = re.compile(r"https?://(localhost|127\.0\.0\.1|keycloak|minio|redis|postgres|"
                         r"safeface\.|www\.grip\.unina\.it/download/LICENSE|arxiv\.org)")
    forbidden_calls = ("hf_hub_download", "load_state_dict_from_url", "download_url_to_file",
                       "urlretrieve", "requests.get", "snapshot_download")
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"')]+", text):
            assert allowed.match(url) or "github.com" in url, f"{path}: {url}"
        for call in forbidden_calls:
            assert call not in text, f"{path} uses {call}"


def test_api_disables_cdn_docs() -> None:
    from app.main import app

    assert app.docs_url is None and app.redoc_url is None


def test_report_renderer_refuses_external_resources() -> None:
    from app.reports.builder import _refuse_network

    with pytest.raises(ValueError, match="may not fetch"):
        _refuse_network("https://example.com/logo.png")
