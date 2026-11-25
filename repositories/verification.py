from __future__ import annotations

from datetime import datetime

from psycopg import Connection
from psycopg.types.json import Jsonb


def requeue_stale(conn: Connection, minutes: int) -> int:
    return conn.execute(
        "UPDATE verification_jobs SET status = 'QUEUED', locked_by = NULL, locked_at = NULL, "
        "last_error = 'khôi phục job treo (worker dừng giữa chừng)' "
        "WHERE status = 'RUNNING' AND locked_at < now() - make_interval(mins => %s)",
        (minutes,),
    ).rowcount


def lock_next_queued(conn: Connection) -> dict | None:
    return conn.execute(
        "SELECT * FROM verification_jobs WHERE status = 'QUEUED' AND run_after <= now() "
        "ORDER BY run_after, id FOR UPDATE SKIP LOCKED LIMIT 1"
    ).fetchone()


def mark_running(conn: Connection, job_id: int, worker_id: str) -> None:
    conn.execute(
        "UPDATE verification_jobs SET status = 'RUNNING', attempts = attempts + 1, locked_by = %s, locked_at = now() "
        "WHERE id = %s",
        (worker_id, job_id),
    )


def finish_job(conn: Connection, job_id: int, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE verification_jobs SET status = %s, last_error = %s, locked_by = NULL, locked_at = NULL WHERE id = %s",
        (status, error[:500] if error else None, job_id),
    )


def requeue_job(
    conn: Connection, job_id: int, delay_minutes: int, error: str | None
) -> None:
    conn.execute(
        "UPDATE verification_jobs SET status = 'QUEUED', run_after = now() + make_interval(mins => %s), "
        "locked_by = NULL, locked_at = NULL, last_error = %s WHERE id = %s",
        (delay_minutes, error[:500] if error else None, job_id),
    )


def get_record(conn: Connection, record_id: int, for_update: bool = False) -> dict | None:
    return conn.execute(
        "SELECT * FROM attendance_records WHERE id = %s" + (" FOR UPDATE" if for_update else ""), (record_id,)
    ).fetchone()


def get_photo_by_record(conn: Connection, record_id: int) -> dict | None:
    return conn.execute("SELECT * FROM attendance_photos WHERE attendance_record_id = %s", (record_id,)).fetchone()


def set_record_verification(conn: Connection, record_id: int, status: str) -> None:
    conn.execute("UPDATE attendance_records SET verification_status = %s WHERE id = %s", (status, record_id))


def save_ocr_result(
    conn: Connection, record_id: int, *, verification_status: str, photo_taken_at: datetime | None,
    replace_capture_time: bool, flags: list[str],
) -> None:
    conn.execute(
        "UPDATE attendance_records SET verification_status = %s, "
        "photo_taken_at = CASE WHEN %s THEN %s ELSE photo_taken_at END, "
        "punctuality_status = 'NOT_EVALUATED', flags = %s WHERE id = %s",
        (verification_status, replace_capture_time, photo_taken_at, flags, record_id),
    )


def insert_log(conn: Connection, record_id: int, status: str, provider: str = "OCR_SPACE") -> int:
    return conn.execute(
        "INSERT INTO verification_logs (attendance_record_id, provider, status) VALUES (%s, %s, %s) RETURNING id",
        (record_id, provider, status),
    ).fetchone()["id"]


def finish_log(
    conn: Connection, log_id: int, *, status: str, result_text: str | None,
    error: str | None, parsed: dict | None,
) -> None:
    conn.execute(
        "UPDATE verification_logs SET status = %s, result_text = %s, finished_at = now(), "
        "error_message = %s, parsed = %s WHERE id = %s",
        (status, result_text, error[:1000] if error else None,
         Jsonb(parsed) if parsed is not None else None, log_id),
    )


def update_photo_details(
    conn: Connection, photo_id: int, *, code: str | None, lat: float | None, lon: float | None,
    gps_raw: str | None, device: str | None,
) -> None:
    conn.execute(
        "UPDATE attendance_photos SET photo_code = COALESCE(%s, photo_code), latitude = COALESCE(%s, latitude), "
        "longitude = COALESCE(%s, longitude), gps_raw = COALESCE(%s, gps_raw), device_model = COALESCE(%s, device_model) "
        "WHERE id = %s",
        (code, lat, lon, gps_raw, device, photo_id),
    )
