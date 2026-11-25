-- Remove Timemark-only retry history and storage that can be derived or is no longer produced by OCR.
DELETE FROM verification_logs WHERE provider = 'TIMEMARK_WEB';

ALTER TABLE verification_logs
    DROP COLUMN screenshot_reference;

UPDATE verification_logs
SET parsed = parsed - 'status_code'
WHERE provider = 'OCR_SPACE' AND parsed ? 'status_code';

ALTER TABLE verification_jobs
    DROP COLUMN pending_retries;

ALTER TABLE attendance_photos
    DROP COLUMN cloudinary_url;

ALTER TABLE verification_logs
    ALTER COLUMN provider SET DEFAULT 'OCR_SPACE';

-- uq_photo_one_per_record already indexes this column and enforces the same uniqueness.
DROP INDEX idx_photos_record;
