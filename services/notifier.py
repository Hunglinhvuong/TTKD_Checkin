"""Gửi thông báo Telegram từ tiến trình worker (không chạy bot), qua Bot API bằng urllib."""
from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


def reply(token: str, chat_id: int, reply_to_message_id: int | None, text: str) -> bool:
    if not token:
        return False
    body = {"chat_id": chat_id, "text": text, "allow_sending_without_reply": True}
    if reply_to_message_id:
        body["reply_to_message_id"] = reply_to_message_id
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except Exception as exc:  # noqa: BLE001 - không để lỗi thông báo làm hỏng worker; không log URL (chứa token)
        log.warning("Gửi thông báo Telegram thất bại: %s", type(exc).__name__)
        return False


def checkin_message(
    final_status: str | None, reason: str | None, resubmit_allowed: bool, sales_point_name: str
) -> str:
    resend = (
        " Vui lòng gửi lại ảnh check-in."
        if resubmit_allowed
        else " Bạn đã hết số lần gửi ảnh trong buổi này, vui lòng liên hệ admin."
    )
    if reason == "SESSION_MISMATCH":
        return "❌ Check-in không hợp lệ: thời gian trên ảnh thuộc buổi khác với buổi check-in." + resend
    if reason == "NO_CAPTURE_TIME":
        return "❌ Check-in không hợp lệ: không đọc được thời gian trên ảnh." + resend
    if reason == "OCR_READ_FAILED":
        return "❌ Check-in không hợp lệ: không đọc được thông tin thời gian từ ảnh." + resend
    if final_status == "VALID":
        return f"✅ Check-in hợp lệ. Điểm bán: {sales_point_name}."
    return "❌ Check-in không hợp lệ." + resend
