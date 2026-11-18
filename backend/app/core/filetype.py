"""File type detection by magic bytes (never by filename or client MIME type).

Only formats listed in SRS FR-1.2 are accepted. Anything else is rejected
before it reaches storage or any parser.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.base import MediaType

# Bytes needed to identify every supported format.
SNIFF_BYTES = 64

_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis", b"avif"}
_MP4_BRANDS = {b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash", b"mmp4"}
_M4A_BRANDS = {b"M4A ", b"M4B "}


@dataclass(frozen=True)
class DetectedType:
    media_type: MediaType
    mime: str
    label: str


def detect(head: bytes) -> DetectedType | None:
    """Identify a file from its first bytes. Returns ``None`` if unsupported."""
    if head.startswith(b"\xff\xd8\xff"):
        return DetectedType(MediaType.IMAGE, "image/jpeg", "JPEG")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedType(MediaType.IMAGE, "image/png", "PNG")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return DetectedType(MediaType.IMAGE, "image/webp", "WEBP")
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return DetectedType(MediaType.AUDIO, "audio/wav", "WAV")
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _HEIF_BRANDS:
            return DetectedType(MediaType.IMAGE, "image/heic", "HEIC/HEIF")
        if brand == b"qt  ":
            return DetectedType(MediaType.VIDEO, "video/quicktime", "MOV")
        if brand in _M4A_BRANDS:
            return DetectedType(MediaType.AUDIO, "audio/mp4", "M4A")
        if brand in _MP4_BRANDS:
            return DetectedType(MediaType.VIDEO, "video/mp4", "MP4")
        return None
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        kind = "WEBM" if b"webm" in head else "MKV"
        mime = "video/webm" if kind == "WEBM" else "video/x-matroska"
        return DetectedType(MediaType.VIDEO, mime, kind)
    if head.startswith(b"OggS"):
        return DetectedType(MediaType.AUDIO, "audio/ogg", "OGG")
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return DetectedType(MediaType.AUDIO, "audio/mpeg", "MP3")
    return None
