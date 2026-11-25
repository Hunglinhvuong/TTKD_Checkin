import pandas as pd
import streamlit as st

from dashboard import common, data
from dashboard.util import FINAL, SESSION, normalize_range


def render() -> None:
    common.show_flash()
    st.title("📍 Bản đồ điểm bán")
    st.caption("Vị trí GPS được đọc từ ảnh OCR của các lượt điểm danh.")

    tz = common.tz()
    today = data.local_today(tz)
    users = common.cached(data.users_basic)()
    names = {user["id"]: user["full_name"] for user in users}

    filters = st.columns([2, 1, 2])
    d1, d2 = normalize_range(
        filters[0].date_input(
            "Khoảng ngày",
            value=(today - pd.Timedelta(days=29), today),
            format="DD/MM/YYYY",
        ),
        today,
    )
    sessions = filters[1].multiselect("Buổi", list(SESSION), format_func=SESSION.get)
    picked = filters[2].multiselect("Nhân viên", list(names), format_func=names.get)

    rows = common.cached(data.sales_point_map_rows)(d1, d2, tuple(sessions), tuple(picked))
    count_text = f"{len(rows)} lượt có tọa độ"
    if len(rows) >= 5000:
        count_text += " (đã giới hạn 5000 lượt đầu)"
    st.caption(count_text)
    if not rows:
        st.info("Không có lượt điểm danh nào có tọa độ OCR trong khoảng lọc.")
        return

    df = pd.DataFrame(rows)
    map_data = df[["latitude", "longitude"]].rename(columns={"latitude": "lat", "longitude": "lon"})
    st.map(map_data, use_container_width=True)

    df["attendance_date"] = pd.to_datetime(df["attendance_date"]).dt.strftime("%d/%m/%Y")
    df["session"] = df["session"].map(SESSION)
    df["final_status"] = df["final_status"].map(lambda status: FINAL.get(status, status))
    df["sales_point_name"] = df["sales_point_name"].fillna("—")
    df = df.rename(columns={
        "id": "ID",
        "attendance_date": "Ngày",
        "session": "Buổi",
        "full_name": "Nhân viên",
        "sales_point_name": "Điểm bán",
        "latitude": "Vĩ độ (lat)",
        "longitude": "Kinh độ (long)",
        "final_status": "Kết quả",
    })
    st.dataframe(df, use_container_width=True, hide_index=True)
