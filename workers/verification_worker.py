"""Worker OCR ảnh điểm danh: tiến trình độc lập với bot.
Chỉ một worker chạy tại một thời điểm (advisory lock) + nghỉ tối thiểu giữa các lượt để không gửi dồn dập."""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from pathlib import Path

import psycopg

from config.settings import ConfigError, Settings
from database.connection import close_pool, init_pool
from services import attendance, notifier, photo_storage, verification
from services.ocr_space_verifier import OCRSpaceVerifier
from services.verification_types import VerificationOutcome, Verifier

log = logging.getLogger(__name__)
WORKER_LOCK_ID = 726_002
SUPPORTED_EXT = {"jpg", "jpeg", "png", "gif"}
POLL_S = 3


def _manual(reason: str) -> VerificationOutcome:
    return VerificationOutcome("MANUAL_REVIEW", error=reason)


def process_job(job: verification.ClaimedJob, verifier: Verifier, settings: Settings) -> VerificationOutcome:
    photo = job.photo or {}
    ext = (photo.get("file_ext") or "").lower()
    size = photo.get("file_size_bytes") or 0
    if ext not in SUPPORTED_EXT or size > settings.ocr_space_max_file_bytes:
        return _manual(f"UNSUPPORTED_FOR_OCR_SPACE: định dạng={ext!r}, kích thước={size}")

    path = photo.get("temp_path")
    if not (path and Path(path).exists()):
        try:
            path = photo_storage.fetch_from_cloudinary(photo, settings.upload_tmp_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("Không lấy được file ảnh %s: %s", photo.get("id"), exc)
            return _manual(f"NO_IMAGE_FILE: {type(exc).__name__}: {exc}"[:500])

    try:
        return verifier.verify(path)
    except Exception as exc:  # noqa: BLE001
        log.exception("Lỗi không lường trước khi xác minh bản ghi %s", job.record_id)
        return VerificationOutcome("AUTOMATION_ERROR", error=f"{type(exc).__name__}: {exc}"[:500])


def _notify_checkin(settings: Settings, result: attendance.CheckinCompletion) -> None:
    notifier.reply(
        settings.bot_token,
        result.telegram_chat_id,
        result.telegram_message_id,
        notifier.checkin_message(
            result.final_status,
            result.reason,
            result.resubmit_allowed,
            result.sales_point_name,
        ),
    )


def run_worker(settings: Settings) -> int:
    settings.require("ocr_space_api_key")
    init_pool(settings)
    try:
        photo_storage.configure(settings)
    except ConfigError:
        log.warning("Chưa cấu hình Cloudinary: không thể tải lại ảnh khi mất file tạm")

    lock_conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        if not lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (WORKER_LOCK_ID,)).fetchone()[0]:
            log.error("Đã có worker khác đang chạy, thoát.")
            return 1

        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        next_local_cleanup = 0.0
        next_checkin_sweep = 0.0
        log.info("Worker %s bắt đầu", worker_id)

        with OCRSpaceVerifier(
            settings.ocr_space_api_key,
            timeout_s=settings.ocr_space_timeout_s,
            timezone_name=settings.timezone,
        ) as verifier:
            while not stop.is_set():
                if time.time() >= next_local_cleanup:
                    try:
                        photo_storage.cleanup_expired_local(
                            settings.local_photo_dir, settings.local_photo_retention_days
                        )
                    except Exception:
                        log.exception("Không dọn được ảnh local quá hạn")
                        next_local_cleanup = time.time() + 3600
                    else:
                        next_local_cleanup = time.time() + 24 * 60 * 60
                try:
                    if time.monotonic() >= next_checkin_sweep:
                        for completed in attendance.complete_pending_checkins(settings.timezone):
                            _notify_checkin(settings, completed)
                        next_checkin_sweep = time.monotonic() + 10
                    job = verification.claim_next(worker_id)
                    if job is None:
                        stop.wait(POLL_S)
                        continue
                    outcome = process_job(job, verifier, settings)
                    comp = verification.complete(job, outcome, settings.timezone)
                    log.info("Bản ghi %s: %s (lượt %d/%d, %s)", job.record_id, outcome.status, job.attempts,
                             job.max_attempts, comp.kind)
                    if comp.kind == "FINAL":
                        if job.photo:
                            photo_storage.cleanup_temp_if_done(job.photo["id"])
                        if comp.checkin:
                            _notify_checkin(settings, comp.checkin)
                    stop.wait(settings.ocr_space_min_interval_s)
                except Exception:  # noqa: BLE001
                    log.exception("Lỗi vòng lặp worker")
                    stop.wait(10)
        log.info("Worker dừng")
        return 0
    finally:
        lock_conn.close()
        close_pool()
