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


def message_for(
    verification_status: str, final_status: str | None, reason: str | None = None, deadline=None,
    resubmit_allowed: bool = True, capture_date=None, expected_date=None,
) -> str:
    resend = (
        " Vui lòng chụp lại ảnh có hiển thị ngày giờ và gửi ảnh khác."
        if resubmit_allowed
        else " Bạn đã hết số lần gửi ảnh trong buổi này, vui lòng liên hệ admin."
    )
    if reason == "DATE_MISMATCH":  # ngày chụp đọc được không khớp ngày điểm danh
        cd = f"{capture_date:%d/%m/%Y}" if capture_date else "?"
        ed = f"{expected_date:%d/%m/%Y}" if expected_date else "?"
        base = f"❌ Ngày chụp đọc từ ảnh ({cd}) không phải ngày điểm danh ({ed})."
        return base + resend
    if reason == "SESSION_MISMATCH":
        return "❌ Buổi chụp đọc từ ảnh không khớp buổi điểm danh." + resend
    if reason == "OUTSIDE_SALES_POINT_RADIUS":
        return "⚠️ Vị trí GPS trong ảnh nằm ngoài bán kính điểm bán cho phép. Bản ghi đang chờ admin kiểm tra."
    if verification_status == "VERIFIED_AUTHENTIC" and final_status == "VALID":
        return "✅ Ảnh điểm danh đã được xác minh."
    if verification_status == "VERIFIED_AUTHENTIC" and final_status == "LATE":
        return "⏰ Điểm danh bị tính muộn" + (f" (hạn {deadline:%H:%M})." if deadline else ".")
    if verification_status == "VERIFIED_AUTHENTIC" and final_status == "RECEIVED":
        return "✅ OCR.Space đã đọc được thông tin ảnh; hệ thống sẽ tiếp tục xử lý."
    if verification_status == "VERIFIED_FAKE":
        if reason == "EDITED":
            return "❌ Ảnh không được xác nhận là nguyên bản, không được chấp nhận." + resend
        return "❌ Ảnh không vượt qua bước xác minh." + resend
    if verification_status == "UNABLE_TO_VERIFY" and reason == "NO_VALID_CODE":
        return "❌ Ảnh không có code hợp lệ." + resend
    if final_status == "REJECTED":
        return "❌ Ảnh bị từ chối." + resend
    return "⚠️ Ảnh cần admin kiểm tra."
