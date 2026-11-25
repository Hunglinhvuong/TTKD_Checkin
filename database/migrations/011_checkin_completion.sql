ALTER TABLE attendance_records
    ADD COLUMN checkin_completed_at TIMESTAMPTZ;

UPDATE attendance_records
SET checkin_completed_at = processed_at
WHERE sales_point_name IS NOT NULL AND processed_at IS NOT NULL;
