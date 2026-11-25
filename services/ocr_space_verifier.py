"""Đọc ngày giờ và tọa độ từ ảnh điểm danh bằng API OCR.space."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from services.verification_types import VerificationOutcome, parse_gps

log = logging.getLogger(__name__)

API_URL = "https://api.ocr.space/parse/image"
_DATE_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?!\d)")
_DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):([0-5]\d)(?::([0-5]\d))?\s*(AM|PM)?(?!\w)", re.I)
_GPS_RE = re.compile(
    r"(?<![\d/])(-?\d{1,3}(?:\.\s*\d+)?)\s*[,;]\s*(-?\d{1,3}(?:\.\s*\d+)?)(?!\d)"
)
MIN_GPS_DECIMAL_PLACES = 5
_PHOTO_CODE_RE = re.compile(r"\bPhoto\s*Code\s*[:：]?\s*([A-Za-z0-9]{6,32})\b", re.I)
_LABELS = ("Capture Time", "GPS", "Photo Code", "Device Model", "Location", "Software Provider")
_MAX_RESPONSE_BYTES = 2_000_000


class OCRSpaceError(RuntimeError):
    """OCR.space request failed or returned an invalid response."""


@dataclass(frozen=True)
class ParsedOCR:
    fields: dict[str, str | None]
    capture_time: datetime | None
    photo_code: str | None
    gps_state: str
    latitude: float | None
    longitude: float | None


def parse_ocr_text(text: str, timezone_name: str = "Asia/Ho_Chi_Minh") -> ParsedOCR:
    """Extract the attendance timestamp, GPS pair, and labeled photo code from OCR text."""
    fields = {label: None for label in _LABELS}

    date_values: set[date] = set()
    for match in _DATE_DMY_RE.finditer(text):
        day, month, year = (int(value) for value in match.groups())
        try:
            date_values.add(date(year, month, day))
        except ValueError:
            continue
    for match in _DATE_ISO_RE.finditer(text):
        year, month, day = (int(value) for value in match.groups())
        try:
            date_values.add(date(year, month, day))
        except ValueError:
            continue

    time_values: set[time] = set()
    for match in _TIME_RE.finditer(text):
        hour, minute = int(match.group(1)), int(match.group(2))
        second = int(match.group(3) or 0)
        meridian = (match.group(4) or "").upper()
        if meridian:
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if meridian == "PM" else 0)
        elif hour > 23:
            continue
        time_values.add(time(hour, minute, second))

    capture_time = None
    if len(date_values) == 1 and len(time_values) == 1:
        capture_date = next(iter(date_values))
        capture_clock = next(iter(time_values))
        capture_time = datetime.combine(capture_date, capture_clock, tzinfo=ZoneInfo(timezone_name))
        fields["Capture Time"] = f"{capture_date:%d/%m/%Y} {capture_clock:%H:%M:%S}"

    gps_matches = list(dict.fromkeys(match.group(0).strip() for match in _GPS_RE.finditer(text)))
    gps_raw = gps_matches[0] if len(gps_matches) == 1 else None
    gps_state, latitude, longitude = parse_gps(
        gps_raw, min_decimal_places=MIN_GPS_DECIMAL_PLACES
    )
    if len(gps_matches) > 1:
        gps_state = "UNPARSEABLE"
    fields["GPS"] = gps_raw
    if gps_raw and gps_state == "OK":
        fields["Location"] = gps_raw

    code = _PHOTO_CODE_RE.search(text)
    photo_code = code.group(1) if code else None
    fields["Photo Code"] = photo_code

    return ParsedOCR(fields, capture_time, photo_code, gps_state, latitude, longitude)


def _multipart_body(image_path: str, boundary: str) -> bytes:
    path = Path(image_path)
    filename = path.name.replace('"', "_")
    image = path.read_bytes()
    fields = {
        "language": "auto",
        "OCREngine": "2",
        "isOverlayRequired": "false",
        "detectOrientation": "true",
        "scale": "true",
    }
    parts = []
    for name, value in fields.items():
        parts.extend((
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode(),
            b"\r\n",
        ))
    parts.extend((
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {mimetypes.guess_type(filename)[0] or 'application/octet-stream'}\r\n\r\n".encode(),
        image,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ))
    return b"".join(parts)


def _extract_text(response: object) -> str:
    if not isinstance(response, dict):
        raise OCRSpaceError("API trả về JSON không đúng cấu trúc")
    errored = response.get("IsErroredOnProcessing")
    if errored is True or str(errored).lower() == "true":
        detail = response.get("ErrorMessage") or response.get("ErrorDetails") or "không có chi tiết"
        raise OCRSpaceError(f"OCR.Space từ chối ảnh: {detail}")
    try:
        exit_code = int(response.get("OCRExitCode", 1))
    except (TypeError, ValueError) as exc:
        raise OCRSpaceError("API trả về OCRExitCode không hợp lệ") from exc
    if exit_code not in (1, 2):
        detail = response.get("ErrorMessage") or response.get("ErrorDetails") or f"OCRExitCode={exit_code}"
        raise OCRSpaceError(f"OCR.Space xử lý ảnh thất bại: {detail}")

    results = response.get("ParsedResults") or []
    if not isinstance(results, list):
        raise OCRSpaceError("API trả về ParsedResults không hợp lệ")
    texts = [item.get("ParsedText", "") for item in results if isinstance(item, dict)]
    return "\n".join(value for value in texts if isinstance(value, str))


class OCRSpaceVerifier:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: int = 60,
        timezone_name: str = "Asia/Ho_Chi_Minh",
        endpoint: str = API_URL,
    ) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.timezone_name = timezone_name
        self.endpoint = endpoint

    def __enter__(self) -> "OCRSpaceVerifier":
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def verify(self, image_path: str) -> VerificationOutcome:
        boundary = f"----OCRSpace{uuid.uuid4().hex}"
        request = urllib.request.Request(
            self.endpoint,
            data=_multipart_body(image_path, boundary),
            headers={
                "apikey": self.api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise OCRSpaceError("Phản hồi OCR.Space vượt quá giới hạn kích thước")
            api_response = json.loads(payload)
            text = _extract_text(api_response)
        except urllib.error.HTTPError as exc:
            return VerificationOutcome("AUTOMATION_ERROR", error=f"OCR_SPACE_HTTP_{exc.code}")
        except urllib.error.URLError as exc:
            return VerificationOutcome("AUTOMATION_ERROR", error=f"OCR_SPACE_CONNECTION_ERROR: {exc.reason}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return VerificationOutcome("AUTOMATION_ERROR", error=f"OCR_SPACE_INVALID_JSON: {exc}")
        except OCRSpaceError as exc:
            return VerificationOutcome("AUTOMATION_ERROR", error=f"OCR_SPACE_ERROR: {exc}")

        try:
            parsed = parse_ocr_text(text, self.timezone_name)
        except (ValueError, KeyError) as exc:
            log.exception("Cấu hình múi giờ OCR.Space không hợp lệ")
            return VerificationOutcome("AUTOMATION_ERROR", error=f"OCR_SPACE_PARSE_ERROR: {exc}")
        return VerificationOutcome(
            status="VERIFIED_AUTHENTIC",
            status_text="OCR_SPACE",
            result_text=text[:4000],
            fields=parsed.fields,
            capture_time=parsed.capture_time,
            photo_code=parsed.photo_code,
            latitude=parsed.latitude,
            longitude=parsed.longitude,
            gps_state=parsed.gps_state,
            reason="OCR_ONLY",
        )
