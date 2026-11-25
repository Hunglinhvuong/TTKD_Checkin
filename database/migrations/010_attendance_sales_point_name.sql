ALTER TABLE attendance_records
    ADD COLUMN sales_point_name TEXT,
    ADD CONSTRAINT ck_attendance_sales_point_name
        CHECK (sales_point_name IS NULL OR length(btrim(sales_point_name)) BETWEEN 1 AND 200);
