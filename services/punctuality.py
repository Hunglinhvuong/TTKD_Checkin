"""Tương thích giao diện đánh giá cũ; điểm danh hiện không xét vị trí hoặc đúng giờ."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

# Cờ cũ cần xóa khi xác minh lại các bản ghi đã được đánh giá theo quy tắc trước đây.
EVAL_FLAGS = frozenset({
    "NO_CAPTURE_TIME", "GPS_UNREADABLE", "CAPTURE_DATE_MISMATCH", "CAPTURE_SESSION_MISMATCH",
    "CAPTURE_AFTER_RECEIVED", "NO_SALES_POINTS", "OUTSIDE_SALES_POINT_RADIUS",
})


@dataclass(frozen=True)
class Evaluation:
    punctuality: str  # NOT_EVALUATED
    final_status: str  # VALID | LATE | PENDING_REVIEW
    distance_km: float | None
    deadline: time | None
    flags: tuple[str, ...]
    reason: str


def evaluate() -> Evaluation:
    return Evaluation(
        "NOT_EVALUATED", "VALID", None, None, (),
        "Không đánh giá vị trí hoặc đúng giờ",
    )
