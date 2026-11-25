"""Shared result types and GPS parsing for the current OCR verification flow."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

_NO_GPS = {"", "no data", "unknown", "n/a", "na", "-", "--", "none", "null"}
_GPS_RE = re.compile(
    r"^\s*(-?\d{1,3}(?:\.\s*\d+)?)\s*[,;/ ]\s*(-?\d{1,3}(?:\.\s*\d+)?)\s*$"
)


@dataclass
class VerificationOutcome:
    status: str
    status_text: str | None = None
    result_text: str | None = None
    fields: dict[str, str | None] = field(default_factory=dict)
    capture_time: datetime | None = None
    photo_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    gps_state: str = "NONE"
    error: str | None = None
    reason: str | None = None


class Verifier(Protocol):
    def verify(self, image_path: str) -> VerificationOutcome: ...


def parse_gps(
    raw: str | None, *, min_decimal_places: int = 0
) -> tuple[str, float | None, float | None]:
    """Return whether a coordinate pair is absent, valid, or not reliably parseable."""
    if raw is None or raw.strip().lower() in _NO_GPS:
        return "NONE", None, None
    match = _GPS_RE.match(raw)
    if match:
        coordinates = tuple(re.sub(r"\s+", "", value) for value in match.groups())
        latitude, longitude = (float(value) for value in coordinates)
        precision = tuple(
            len(value.partition(".")[2]) if "." in value else 0
            for value in coordinates
        )
        if (
            -90 <= latitude <= 90
            and -180 <= longitude <= 180
            and all(places >= min_decimal_places for places in precision)
        ):
            return "OK", latitude, longitude
    return "UNPARSEABLE", None, None
