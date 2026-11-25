"""Hàng đợi OCR (PostgreSQL, FOR UPDATE SKIP LOCKED) và ghi kết quả. Không phụ thuộc dịch vụ OCR/Telegram."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time

from database.connection import get_conn
from repositories import audit, verification as repo
from services import punctuality
from services import attendance as attendance_service
from services.timemark_verifier import VerificationOutcome

log = logging.getLogger(__name__)
STALE_MINUTES = 10
MAX_BACKOFF_MINUTES = 30
_PLACEHOLDERS = {"unknown", "--", "n/a", ""}


@dataclass(frozen=True)
class ClaimedJob:
    job_id: int
    record_id: int
    attempts: int
    max_attempts: int
    log_id: int
    record: dict
    photo: dict


@dataclass(frozen=True)
class Completion:
    kind: str  # FINAL | RETRY
    verification_status: str
    final_status: str | None
    reason: str | None = None
    deadline: time | None = None  # giữ cho tương thích với log/xử lý cũ
    punctuality: str | None = None
    resubmit_allowed: bool = False
    capture_date: date | None = None
    expected_date: date | None = None
    checkin: attendance_service.CheckinCompletion | None = None


def claim_next(worker_id: str) -> ClaimedJob | None:
    with get_conn() as conn:
        repo.requeue_stale(conn, STALE_MINUTES)
        while True:
            job = repo.lock_next_queued(conn)
            if job is None:
                return None
            if job["attempts"] >= job["max_attempts"]:  # đã tiêu hết lượt (vd worker crash lặp lại)
                _fail_exhausted(conn, job)
                continue
            repo.mark_running(conn, job["id"], worker_id)
            repo.set_record_verification(conn, job["attendance_record_id"], "PROCESSING")
            log_id = repo.insert_log(conn, job["attendance_record_id"], "PROCESSING")
            return ClaimedJob(
                job_id=job["id"],
                record_id=job["attendance_record_id"],
                attempts=job["attempts"] + 1,
                max_attempts=job["max_attempts"],
                log_id=log_id,
                record=repo.get_record(conn, job["attendance_record_id"]),
                photo=repo.get_photo_by_record(conn, job["attendance_record_id"]),
            )


def _fail_exhausted(conn, job: dict) -> None:
    rid = job["attendance_record_id"]
    msg = "Vượt số lần thử xác minh (worker crash/treo nhiều lần)"
    record = repo.get_record(conn, rid, for_update=True)
    repo.finish_job(conn, job["id"], "FAILED", msg)
    log_id = repo.insert_log(conn, rid, "AUTOMATION_ERROR")
    repo.finish_log(conn, log_id, status="AUTOMATION_ERROR", result_text=None, error=msg, parsed=None)
    repo.save_ocr_result(
        conn,
        rid,
        verification_status="AUTOMATION_ERROR",
        photo_taken_at=None,
        replace_capture_time=False,
        flags=list(record["flags"]),
    )
    audit.add(conn, action="VERIFICATION_EXHAUSTED", entity_type="attendance_records", entity_id=rid,
              actor_type="SYSTEM", new_value={"verification_status": "AUTOMATION_ERROR"})


def _parsed_json(o: VerificationOutcome) -> dict:
    return {
        "status_text": o.status_text,
        "status_code": o.status_code,
        "reason": o.reason,
        "fields": o.fields,
        "gps_state": o.gps_state,
        "capture_time": o.capture_time.isoformat() if o.capture_time else None,
        "photo_code": o.photo_code,
    }


def _clean(value: str | None) -> str | None:
    return None if value is None or value.strip().lower() in _PLACEHOLDERS else value


def complete(
    job: ClaimedJob,
    outcome: VerificationOutcome,
    tz: str = "Asia/Ho_Chi_Minh",
) -> Completion:
    """Ghi kết quả OCR; chỉ kiểm tra buổi, không chấm vị trí hoặc đúng giờ/muộn."""
    with get_conn() as conn:
        record = repo.get_record(conn, job.record_id, for_update=True)

        if outcome.status == "AUTOMATION_ERROR" and job.attempts < job.max_attempts:
            repo.finish_log(conn, job.log_id, status="AUTOMATION_ERROR", result_text=outcome.result_text,
                            error=outcome.error, parsed=None)
            repo.requeue_job(conn, job.job_id, min(2 ** job.attempts, MAX_BACKOFF_MINUTES), outcome.error)
            repo.set_record_verification(conn, job.record_id, "PENDING")
            return Completion("RETRY", "PENDING", None, "AUTOMATION_ERROR")

        ev = None
        flags = [flag for flag in record["flags"] if flag not in punctuality.EVAL_FLAGS]
        if outcome.status == "VERIFIED_AUTHENTIC":
            ev = punctuality.evaluate(
                session=record["session"],
                capture_time=outcome.capture_time,
                tz=tz,
            )
            flags += [f for f in ev.flags if f not in flags]
        replace_capture_time = outcome.status == "VERIFIED_AUTHENTIC"
        repo.save_ocr_result(
            conn,
            job.record_id,
            verification_status=outcome.status,
            photo_taken_at=outcome.capture_time,
            replace_capture_time=replace_capture_time,
            flags=flags,
        )
        updated_record = {
            **record,
            "verification_status": outcome.status,
            "photo_taken_at": outcome.capture_time if replace_capture_time else record["photo_taken_at"],
            "flags": flags,
        }
        if job.photo:
            repo.update_photo_details(
                conn, job.photo["id"], code=outcome.photo_code, lat=outcome.latitude, lon=outcome.longitude,
                gps_raw=_clean(outcome.fields.get("GPS")), device=_clean(outcome.fields.get("Device Model")),
            )
        repo.finish_log(conn, job.log_id, status=outcome.status, result_text=outcome.result_text,
                        error=outcome.error, parsed=_parsed_json(outcome))
        repo.finish_job(conn, job.job_id, "FAILED" if outcome.status == "AUTOMATION_ERROR" else "DONE", outcome.error)
        checkin = attendance_service.complete_checkin(conn, updated_record, tz)
        final = checkin.final_status if checkin else record["final_status"]
        audit.add(
            conn, action="VERIFICATION_COMPLETED", entity_type="attendance_records", entity_id=job.record_id,
            actor_type="SYSTEM",
            old_value={"final_status": record["final_status"]},
            new_value={
                "verification_status": outcome.status, "final_status": final, "flags": flags,
                "reason": outcome.reason, "status_code": outcome.status_code,
                **({"punctuality": ev.punctuality, "distance_km": ev.distance_km,
                    "deadline": ev.deadline.isoformat() if ev.deadline else None, "evaluation": ev.reason} if ev else {}),
            },
        )
        return Completion(
            "FINAL", outcome.status, final,
            checkin.reason if checkin else None,
            deadline=ev.deadline if ev else None,
            punctuality=ev.punctuality if ev else None,
            resubmit_allowed=checkin.resubmit_allowed if checkin else False,
            checkin=checkin,
        )
