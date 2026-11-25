"""Kiểm tra buổi từ giờ chụp; không xét vị trí hoặc đúng giờ/muộn."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from services.workcalendar import session_for, to_local

# Cờ cũ cần xóa khi xác minh lại các bản ghi đã được đánh giá theo quy tắc trước đây.
EVAL_FLAGS = frozenset({
    "NO_CAPTURE_TIME", "GPS_UNREADABLE", "CAPTURE_DATE_MISMATCH", "CAPTURE_SESSION_MISMATCH",
    "CAPTURE_AFTER_RECEIVED", "NO_SALES_POINTS", "OUTSIDE_SALES_POINT_RADIUS",
})


@dataclass(frozen=True)
class Evaluation:
    punctuality: str  # NOT_EVALUATED
    final_status: str  # VALID | REJECTED
    distance_km: float | None
    deadline: time | None
    flags: tuple[str, ...]
    reason: str


def evaluate(*, session: str, capture_time: datetime | None, tz: str) -> Evaluation:
    if capture_time is None:
        return Evaluation(
            "NOT_EVALUATED",
            "REJECTED",
            None,
            None,
            ("NO_CAPTURE_TIME",),
            "Không đọc được thời gian trên ảnh",
        )
    if session_for(to_local(capture_time, tz)) != session:
        return Evaluation(
            "NOT_EVALUATED",
            "REJECTED",
            None,
            None,
            ("CAPTURE_SESSION_MISMATCH",),
            "Buổi chụp từ ảnh không khớp buổi check-in",
        )
    return Evaluation(
        "NOT_EVALUATED", "VALID", None, None, (),
        "Không đánh giá vị trí hoặc đúng giờ/muộn",
    )
