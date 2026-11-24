"""U&I Logistics | AI Smart Follow-up & Quotation Tracking - academic prototype.

Run: streamlit run app.py
Requires: streamlit, pandas, plotly (see requirements.txt).
This is a DEMO: all seed records are fictional; classification is keyword-based,
not a live AI model; no email is sent and no customer data is synchronized.
"""
from __future__ import annotations

import html
import re
import sqlite3
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "data" / "quotation_demo.db"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")
OPEN_STATUSES = {"Đã gửi", "Chưa phản hồi"}
REPLIED_STATUSES = {"Đã phản hồi", "Đã booking", "Từ chối"}
ALL_STATUSES = ["Đã gửi", "Chưa phản hồi", "Đã phản hồi", "Đã booking", "Từ chối"]
STATUS_COLORS = {
    "Đã gửi": "#64748b", "Chưa phản hồi": "#d97706", "Đã phản hồi": "#2563eb",
    "Đã booking": "#15803d", "Từ chối": "#dc2626",
}


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def read_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def human_dt(value: str | None) -> str:
    parsed = read_dt(value)
    return parsed.strftime("%d/%m/%Y %H:%M") if parsed else "—"


def db_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def add_history(conn: sqlite3.Connection, quote_id: str, action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO history(quote_id, created_at, action, detail) VALUES(?, ?, ?, ?)",
        (quote_id, iso(now()), action, detail),
    )


def initialize() -> None:
    with db_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS quotations (
            id TEXT PRIMARY KEY,
            customer TEXT NOT NULL,
            contact TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            commodity TEXT NOT NULL DEFAULT '',
            quoted_usd REAL NOT NULL DEFAULT 0,
            sent_at TEXT NOT NULL,
            followup_hours INTEGER NOT NULL DEFAULT 48,
            last_contact_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Đã gửi',
            reply_text TEXT NOT NULL DEFAULT '',
            reply_category TEXT NOT NULL DEFAULT '',
            recommendation TEXT NOT NULL DEFAULT '',
            first_reply_at TEXT
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL,
            FOREIGN KEY(quote_id) REFERENCES quotations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_id TEXT NOT NULL,
            title TEXT NOT NULL,
            due_at TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'Trung bình',
            status TEXT NOT NULL DEFAULT 'Cần làm',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY(quote_id) REFERENCES quotations(id) ON DELETE CASCADE
        );
        """)
        if conn.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]:
            return
        samples = [
            ("QT-026-001", "ABC Trading", "Ms. Anna", "anna@example.com", "Cát Lái", "Los Angeles", "Nội thất gỗ", 2860, 4, "Chưa phản hồi", ""),
            ("QT-026-002", "Pacific Furniture", "Mr. Brian", "brian@example.com", "Cát Lái", "Long Beach", "Bàn ghế gỗ", 2690, 2, "Đã phản hồi", "Could you offer a lower ocean freight rate?"),
            ("QT-026-003", "Sunrise Wood", "Ms. Cindy", "cindy@example.com", "Cát Lái", "New York", "Đồ gỗ nội thất", 3130, 6, "Chưa phản hồi", ""),
            ("QT-026-004", "Green Ocean Co.", "Mr. David", "david@example.com", "Cát Lái", "Los Angeles", "Tủ gỗ", 2790, 3, "Đã booking", "We agree with the quotation, please proceed with booking."),
            ("QT-026-005", "Global Timber", "Ms. Eva", "eva@example.com", "Cái Mép", "Seattle", "Ván ép", 2430, 8, "Từ chối", "We have decided not to proceed with this quotation."),
            ("QT-026-006", "Northstar Import", "Mr. Frank", "frank@example.com", "Cát Lái", "Los Angeles", "Ghế gỗ", 2720, 1, "Đã gửi", ""),
            ("QT-026-007", "Golden Oak", "Ms. Grace", "grace@example.com", "Cát Lái", "Oakland", "Bàn gỗ", 2960, 5, "Đã phản hồi", "What are the ETD, ETA and transit time?"),
            ("QT-026-008", "Oceanlink Trade", "Mr. Henry", "henry@example.com", "Cái Mép", "Los Angeles", "Tủ kệ gỗ", 2880, 9, "Chưa phản hồi", ""),
            ("QT-026-009", "Delta Home", "Ms. Iris", "iris@example.com", "Cát Lái", "Houston", "Nội thất phòng ngủ", 3280, 2, "Đã phản hồi", "Please clarify free time and demurrage conditions."),
            ("QT-026-010", "Maple Export", "Mr. Jack", "jack@example.com", "Cát Lái", "Los Angeles", "Đồ gỗ", 2630, 7, "Chưa phản hồi", ""),
            ("QT-026-011", "Evergreen Decor", "Ms. Kate", "kate@example.com", "Cát Lái", "Long Beach", "Trang trí gỗ", 2740, 1, "Đã booking", "Confirmed. Please arrange the booking."),
            ("QT-026-012", "Bright Interiors", "Mr. Liam", "liam@example.com", "Cát Lái", "Los Angeles", "Tủ bếp", 2810, 3, "Đã gửi", ""),
        ]
        for code, customer, contact, email, pol, pod, cargo, price, days_ago, status, reply in samples:
            sent = now() - timedelta(days=days_ago, hours=2)
            # Replied quotations have a synthetic first response, other quotations do not.
            replied_at = iso(sent + timedelta(hours=16)) if status in REPLIED_STATUSES else None
            category, recommendation, _ = classify_reply(reply) if reply else ("", "", "")
            conn.execute("""
                INSERT INTO quotations
                (id, customer, contact, email, origin, destination, commodity,
                 quoted_usd, sent_at, followup_hours, last_contact_at, status,
                 reply_text, reply_category, recommendation, first_reply_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (code, customer, contact, email, pol, pod, cargo, price,
                  iso(sent), 48, iso(sent), status, reply, category, recommendation, replied_at))
            add_history(conn, code, "Tạo báo giá demo", f"Tuyến {pol} → {pod}; {price:,.0f} USD")
            if reply:
                add_history(conn, code, "Đã nhận phản hồi (demo)", reply)
        for code, hours_left, priority in [
            ("QT-026-001", -6, "Cao"), ("QT-026-003", -25, "Cao"),
            ("QT-026-006", 18, "Trung bình"), ("QT-026-008", -46, "Cao")
        ]:
            due = now() + timedelta(hours=hours_left)
            conn.execute("""
                INSERT INTO tasks(quote_id,title,due_at,priority,status,created_at)
                VALUES(?,?,?,?,?,?)
            """, (code, "Follow-up khách hàng chưa phản hồi", iso(due), priority,
                  "Cần làm", iso(now())))


def all_quotes() -> list[dict]:
    with db_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM quotations ORDER BY sent_at DESC").fetchall()]


def one_quote(code: str) -> dict | None:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM quotations WHERE id = ?", (code,)).fetchone()
        return dict(row) if row else None


def all_tasks() -> list[dict]:
    with db_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT t.*, q.customer, q.destination, q.status AS quote_status
            FROM tasks t JOIN quotations q ON q.id=t.quote_id
            ORDER BY CASE WHEN t.status='Cần làm' THEN 0 ELSE 1 END, t.due_at ASC
        """).fetchall()]


def get_history(code: str) -> list[dict]:
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT created_at, action, detail FROM history WHERE quote_id=? ORDER BY id DESC", (code,)
        ).fetchall()]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(normalize(phrase) in text for phrase in phrases)


def classify_reply(reply: str) -> tuple[str, str, str]:
    """Offline demo classifier: ordered phrase rules, NOT a trained AI model."""
    t = normalize(reply.strip())
    if not t:
        return ("Chưa phản hồi", "Chờ khách trả lời và theo dõi thời hạn follow-up.", "Chưa phản hồi")
    # Explicit rejection takes precedence over mentioning prices or schedule.
    if has_phrase(t, ("not proceed", "decline", "reject", "not interested", "cancel the quotation",
                      "khong dong y", "tu choi", "khong tiep tuc", "khong su dung")):
        return ("Từ chối báo giá", "Ghi nhận lý do từ chối; hỏi thêm ý kiến khách nếu phù hợp và cập nhật dữ liệu win/loss.", "Từ chối")
    if has_phrase(t, ("please book", "proceed with booking", "we agree", "confirmed", "accept the quote",
                      "dong y bao gia", "xac nhan booking", "chot booking", "dat cho")):
        return ("Khách đồng ý", "Chuyển Sales kiểm tra hiệu lực giá, chỗ và lịch tàu với Pricing/OPS trước khi xác nhận booking.", "Đã booking")
    if has_phrase(t, ("price", "cost", "rate", "freight", "surcharge", "thc", "local charge",
                      "gia cuoc", "gia", "phu phi", "chi phi", "giam gia", "discount")):
        return ("Giá cước và phụ phí", "Sales xác nhận lại mức giá, thời hạn hiệu lực và phụ phí với Pricing trước khi phản hồi.", "Đã phản hồi")
    if has_phrase(t, ("etd", "eta", "sailing", "schedule", "departure", "vessel", "lich tau", "ngay tau")):
        return ("Lịch tàu", "Liên hệ Pricing/OPS kiểm tra lịch tàu, cut-off và chỗ còn trống trước khi trả lời.", "Đã phản hồi")
    if has_phrase(t, ("transit", "delivery time", "lead time", "duration", "thoi gian van chuyen", "bao lau")):
        return ("Thời gian vận chuyển", "Đối chiếu transit time dự kiến với hãng tàu và lưu ý khả năng thay đổi lịch trình.", "Đã phản hồi")
    if has_phrase(t, ("free time", "demurrage", "detention", "incoterms", "payment", "terms",
                      "dieu kien", "thanh toan", "mien luu", "chung tu")):
        return ("Điều kiện dịch vụ", "Kiểm tra điều khoản, free time và phạm vi dịch vụ với bộ phận phụ trách.", "Đã phản hồi")
    return ("Cần Sales kiểm tra", "Chưa đủ cơ sở phân loại; Sales cần đọc nội dung và xác minh nhu cầu trước khi xử lý.", "Đã phản hồi")


def due_at(q: dict) -> datetime:
    return read_dt(q["last_contact_at"]) + timedelta(hours=int(q["followup_hours"]))


def is_overdue(q: dict) -> bool:
    return q["status"] in OPEN_STATUSES and now() >= due_at(q)


def status_display(q: dict) -> str:
    return "🔴 Quá hạn follow-up" if is_overdue(q) else q["status"]


def metrics(quote_rows: list[dict]) -> dict:
    n = len(quote_rows)
    replied = sum(q["status"] in REPLIED_STATUSES for q in quote_rows)
    booked = sum(q["status"] == "Đã booking" for q in quote_rows)
    late = sum(is_overdue(q) for q in quote_rows)
    durations = []
    for q in quote_rows:
        first_reply, sent = read_dt(q["first_reply_at"]), read_dt(q["sent_at"])
        if first_reply and sent and first_reply >= sent:
            durations.append((first_reply - sent).total_seconds() / 3600)
    return {"total": n, "replied": replied, "booked": booked, "late": late,
            "response_rate": replied / n * 100 if n else 0,
            "booking_rate": booked / n * 100 if n else 0,
            "avg_response_hours": sum(durations) / len(durations) if durations else None}


def add_quote(code: str, customer: str, contact: str, email: str, origin: str,
              destination: str, commodity: str, price: float, sent: datetime, followup_hours: int) -> None:
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO quotations (id, customer, contact, email, origin, destination, commodity,
                quoted_usd, sent_at, followup_hours, last_contact_at, status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (code, customer, contact, email, origin, destination, commodity,
              price, iso(sent), followup_hours, iso(sent), "Đã gửi"))
        add_history(conn, code, "Thêm báo giá", f"Giá {price:,.2f} USD; tuyến {origin} → {destination}")


def save_reply(code: str, reply: str, override_status: str | None = None) -> tuple[str, str, str]:
    category, recommendation, proposed = classify_reply(reply)
    final_status = override_status or proposed
    with db_conn() as conn:
        old = conn.execute("SELECT first_reply_at FROM quotations WHERE id=?", (code,)).fetchone()
        if not old:
            raise ValueError("Không tìm thấy báo giá")
        first_reply_at = old["first_reply_at"] or iso(now())
        conn.execute("""
            UPDATE quotations SET reply_text=?, reply_category=?, recommendation=?, status=?, first_reply_at=?
            WHERE id=?
        """, (reply, category, recommendation, final_status, first_reply_at, code))
        add_history(conn, code, "Ghi nhận phản hồi", f"Nhóm: {category}. Trạng thái: {final_status}. Nội dung: {reply}")
        if final_status in {"Từ chối", "Đã booking"}:
            conn.execute("UPDATE tasks SET status='Đã hủy' WHERE quote_id=? AND status='Cần làm'", (code,))
    return category, recommendation, final_status


def follow_up_done(code: str, note: str) -> None:
    with db_conn() as conn:
        conn.execute("UPDATE quotations SET last_contact_at=? WHERE id=?", (iso(now()), code))
        add_history(conn, code, "Sales đã follow-up", note or "Sales ghi nhận đã liên hệ lại")


def add_task(code: str, title: str, due: datetime, priority: str, note: str = "") -> None:
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO tasks(quote_id,title,due_at,priority,status,note,created_at)
            VALUES(?,?,?,?,?,?,?)
        """, (code, title, iso(due), priority, "Cần làm", note, iso(now())))
        add_history(conn, code, "Tạo task follow-up", f"{title}, hạn {human_dt(iso(due))}")


def finish_task(task_id: int) -> None:
    with db_conn() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return
        conn.execute("UPDATE tasks SET status='Hoàn thành',completed_at=? WHERE id=?", (iso(now()), task_id))
        conn.execute("UPDATE quotations SET last_contact_at=? WHERE id=?", (iso(now()), task["quote_id"]))
        add_history(conn, task["quote_id"], "Hoàn thành task follow-up", task["title"])


def store_draft(code: str, content: str) -> None:
    with db_conn() as conn:
        add_history(conn, code, "Lưu bản nháp email", content[:1500])


def draft_email(q: dict, situation: str, tone: str, language: str, extra: str) -> str:
    code = q["id"]
    route = f"{q['origin']} – {q['destination']}"
    contact = q["contact"].strip()
    extra = extra.strip()
    if language == "English":
        salutation = f"Dear {contact}," if contact else "Dear Customer,"
        intro = f"I am following up on quotation {code} for the {route} shipment, sent on {human_dt(q['sent_at'])}."
        messages = {
            "Nhắc nhẹ – chưa phản hồi": "May I kindly ask whether you have had a chance to review our offer? Please let us know if you need any clarification.",
            "Giá cước và phụ phí": "Thank you for your feedback on pricing. We will verify the current freight rate and applicable charges with our Pricing team before confirming any revision.",
            "Lịch tàu và thời gian vận chuyển": "Thank you for your question about the sailing schedule and transit time. We will reconfirm the latest information with our operations team and revert to you.",
            "Điều kiện dịch vụ": "Thank you for asking about the service terms. We will review the applicable conditions and confirm the details with the responsible team.",
            "Xác nhận booking": "Thank you for your confirmation. We will verify the booking availability, quotation validity and shipment details before sending the final confirmation.",
            "Khách hàng từ chối": "Thank you for considering our quotation. We respect your decision and would appreciate any feedback that could help us improve future offers.",
        }
        ending = "Best regards,\nSales Team | U&I Logistics (Demo)" if tone == "Chuyên nghiệp" else "Kind regards,\nSales Team | U&I Logistics (Demo)"
        body = f"Subject: Follow-up – Quotation {code} – {route}\n\n{salutation}\n\n{intro}\n\n{messages[situation]}"
        if extra:
            body += f"\n\nAdditional note: {extra}"
        return f"{body}\n\n{ending}"
    salutation = f"Kính gửi {contact}," if contact else "Kính gửi Quý khách,"
    intro = f"Chúng tôi xin phép liên hệ về báo giá {code} cho tuyến {route}, đã gửi ngày {human_dt(q['sent_at'])}."
    messages = {
        "Nhắc nhẹ – chưa phản hồi": "Không biết Anh/Chị đã có thời gian xem qua báo giá chưa ạ? Nếu cần làm rõ giá cước, lịch tàu hoặc thời gian vận chuyển, chúng tôi rất sẵn lòng hỗ trợ.",
        "Giá cước và phụ phí": "Cảm ơn Anh/Chị đã phản hồi về giá cước. Chúng tôi sẽ kiểm tra lại cước và các khoản phụ phí với bộ phận Pricing trước khi xác nhận thông tin chính thức.",
        "Lịch tàu và thời gian vận chuyển": "Cảm ơn Anh/Chị đã quan tâm đến lịch tàu và thời gian vận chuyển. Chúng tôi sẽ xác nhận lại lịch trình mới nhất với bộ phận phụ trách rồi phản hồi sớm.",
        "Điều kiện dịch vụ": "Cảm ơn Anh/Chị đã trao đổi về điều kiện dịch vụ. Chúng tôi sẽ kiểm tra phạm vi dịch vụ và các điều khoản liên quan trước khi trả lời chi tiết.",
        "Xác nhận booking": "Cảm ơn Anh/Chị đã xác nhận nhu cầu đặt chỗ. Chúng tôi sẽ kiểm tra hiệu lực báo giá, lịch tàu và khả năng nhận chỗ trước khi xác nhận booking.",
        "Khách hàng từ chối": "Cảm ơn Anh/Chị đã dành thời gian xem xét báo giá. Chúng tôi tôn trọng quyết định của Anh/Chị và mong có cơ hội hỗ trợ trong các lô hàng tiếp theo.",
    }
    greeting = "Trân trọng," if tone == "Chuyên nghiệp" else "Cảm ơn Anh/Chị và chúc một ngày tốt lành!\nTrân trọng,"
    body = f"Subject: Follow-up báo giá {code} – {route}\n\n{salutation}\n\n{intro}\n\n{messages[situation]}"
    if extra:
        body += f"\n\nThông tin bổ sung: {extra}"
    return f"{body}\n\n{greeting}\nBộ phận Sales | U&I Logistics (Demo)"


st.set_page_config(page_title="AI Smart Follow-up | CRM Demo", page_icon="🚢", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
:root { color-scheme: light; }
[data-testid="stAppViewContainer"] { background:#f7f9fc; }
[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #e5eaf1; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:#516074; }
[data-testid="stSidebar"] .stRadio label { padding:5px 7px; }
.block-container { padding-top:1.8rem; padding-bottom:3rem; max-width:1440px; }
h1,h2,h3 { color:#152b48; letter-spacing:-.025em; }
div[data-testid="stMetric"] { background:white; border:1px solid #e8edf5; border-radius:14px; padding:19px 22px; box-shadow:0 3px 14px #132a4606; }
div[data-testid="stMetric"] label { color:#64748b; font-size:.83rem; }
div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color:#18345e; font-weight:750; }
div[data-testid="stVerticalBlockBorderWrapper"] > div { border-radius:15px; }
.brand-box { display:flex; align-items:center; gap:12px; padding:13px 5px 25px; }
.brand-symbol { background:linear-gradient(135deg,#153f75,#3a84be); border-radius:13px; width:48px; height:48px; display:flex; align-items:center; justify-content:center; font-size:17px; font-weight:800; color:white; }
.brand-title {font-size:17px;font-weight:800;color:#162c4b;line-height:1.3}
.brand-sub {font-size:11px;color:#8793a5}
.section-caption {font-weight:750;color:#7990a6;letter-spacing:.1em;font-size:11px;margin:10px 0 13px}
.page-kicker {font-size:12px;font-weight:750;color:#3b82bd;letter-spacing:.11em;text-transform:uppercase;margin-bottom:3px}
.page-title {font-size:32px;font-weight:800;color:#122d4d;line-height:1.2;margin-bottom:6px}
.page-desc {color:#65748a;font-size:14px;margin-bottom:22px}
.info-pill {display:inline-block;background:#edf5ff;color:#2869a2;border-radius:50px;padding:4px 10px;font-size:12px;font-weight:700}
.hint {color:#8490a2;font-size:12px;margin-top:15px}
[data-testid="stDataFrame"] {background:white;border-radius:11px;overflow:hidden}
button[kind="primary"] {background:#1f65aa !important; border:0 !important;}
</style>
""", unsafe_allow_html=True)
initialize()


def page_heading(kicker: str, title: str, desc: str) -> None:
    st.markdown(
        f'<div class="page-kicker">{html.escape(kicker)}</div>'
        f'<div class="page-title">{html.escape(title)}</div>'
        f'<div class="page-desc">{html.escape(desc)}</div>',
        unsafe_allow_html=True,
    )


def quote_selector_label(q: dict) -> str:
    return f"{q['id']} · {q['customer']} · {q['origin']} → {q['destination']}"


def quote_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Mã báo giá": q["id"], "Khách hàng": q["customer"],
        "Tuyến": f"{q['origin']} → {q['destination']}",
        "Giá (USD)": q["quoted_usd"], "Ngày gửi": human_dt(q["sent_at"]),
        "Trạng thái": status_display(q),
        "Hạn follow-up": human_dt(iso(due_at(q))) if q["status"] in OPEN_STATUSES else "—",
    } for q in rows])


def page_dashboard() -> None:
    data = all_quotes()
    m = metrics(data)
    page_heading("Sales intelligence / Overview", "Dashboard báo giá", "Theo dõi tỷ lệ phản hồi và hiệu quả follow-up sau báo giá vận tải biển.")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Tổng số báo giá", str(m["total"]))
    c2.metric("Tỷ lệ phản hồi", f'{m["response_rate"]:.1f}%', f'{m["replied"]} báo giá đã phản hồi', delta_color="off")
    c3.metric("Chưa phản hồi quá hạn", str(m["late"]))
    c4.metric("Chuyển đổi booking", f'{m["booking_rate"]:.1f}%', f'{m["booked"]} booking', delta_color="off")
    st.write("")
    left, right = st.columns([1,1.15], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Cơ cấu trạng thái")
            counts = {s: sum(q["status"] == s for q in data) for s in ALL_STATUSES}
            fig = go.Figure(go.Pie(
                labels=list(counts), values=list(counts.values()), hole=.63,
                marker={"colors":[STATUS_COLORS[s] for s in counts]},
                textinfo="percent+label", hovertemplate="%{label}: %{value}<extra></extra>",
            ))
            fig.update_layout(height=315, margin=dict(t=0,b=0,l=0,r=0),
                              legend=dict(orientation="h",y=-.08), paper_bgcolor="#ffffff")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
    with right:
        with st.container(border=True):
            st.subheader("Báo giá theo cảng đích")
            counts = pd.Series([q["destination"] for q in data]).value_counts()
            fig = go.Figure(go.Bar(
                x=counts.index.tolist(), y=counts.values.tolist(),
                marker_color="#3976b4", text=counts.values.tolist(), textposition="outside",
            ))
            fig.update_layout(height=315, margin=dict(t=15,b=30,l=10,r=10),
                              paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                              xaxis_title="Cảng đến", yaxis_title="Số báo giá",
                              yaxis=dict(dtick=1, gridcolor="#e9edf4"))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
    st.subheader("Báo giá cần ưu tiên follow-up")
    urgent = sorted([q for q in data if q["status"] in OPEN_STATUSES and due_at(q) <= now() + timedelta(hours=24)],
                    key=due_at)
    if urgent:
        st.dataframe(quote_table(urgent), hide_index=True, use_container_width=True)
    else:
        st.success("Hiện chưa có báo giá cần follow-up trong 24 giờ tới.")
    st.caption("Tỷ lệ phản hồi = báo giá đã nhận phản hồi (bao gồm booking/từ chối) ÷ tổng báo giá × 100. Tỷ lệ booking = số booking ÷ tổng báo giá × 100.")
    if m["avg_response_hours"] is not None:
        st.caption(f'Thời gian trung bình gửi → nhận phản hồi: {m["avg_response_hours"]:.1f} giờ (theo thời điểm ghi nhận trong bản demo).')
    st.download_button("⬇️ Xuất danh sách báo giá CSV", quote_table(data).to_csv(index=False).encode("utf-8-sig"),
                       "bao_cao_bao_gia.csv", "text/csv")


def page_leads() -> None:
    page_heading("Quotation management / Leads", "Leads & quản lý báo giá", "Tạo báo giá, xem trạng thái và ghi nhận nội dung phản hồi từ khách hàng.")
    rows = all_quotes()
    tab_list, tab_add, tab_detail = st.tabs(["📋 Danh sách báo giá", "➕ Thêm báo giá", "🔍 Chi tiết & phản hồi"])
    with tab_list:
        f1, f2 = st.columns([2,1])
        query = f1.text_input("Tìm kiếm", placeholder="Khách hàng, mã báo giá, tuyến vận chuyển…")
        wanted = f2.selectbox("Lọc trạng thái", ["Tất cả", "Quá hạn follow-up"] + ALL_STATUSES)
        shown = [q for q in rows if normalize(query) in normalize(q["id"] + " " + q["customer"] + " " + q["destination"])
                 and (wanted == "Tất cả" or
                      (wanted == "Quá hạn follow-up" and is_overdue(q)) or q["status"] == wanted)]
        st.caption(f"Hiển thị {len(shown)} / {len(rows)} báo giá")
        if shown:
            st.dataframe(quote_table(shown), hide_index=True, use_container_width=True,
                         column_config={"Giá (USD)": st.column_config.NumberColumn("Giá (USD)", format="%.2f")})
        else:
            st.info("Không tìm thấy báo giá phù hợp.")
    with tab_add:
        with st.form("new_quotation", clear_on_submit=True):
            a,b = st.columns(2)
            code = a.text_input("Mã báo giá *", placeholder="QT-026-013")
            customer = b.text_input("Tên khách hàng *", placeholder="Example Furniture")
            contact = a.text_input("Người liên hệ", placeholder="Ms. Anna")
            email = b.text_input("Email (nếu có)", placeholder="sales@example.com")
            pol = a.text_input("Cảng đi *", value="Cát Lái")
            pod = b.text_input("Cảng đến *", value="Los Angeles")
            cargo = a.text_input("Hàng hóa", value="Đồ gỗ xuất khẩu")
            price = b.number_input("Giá báo (USD)", min_value=0.0, max_value=100000000.0, step=10.0, value=2800.0)
            d1,d2,d3 = st.columns(3)
            sent_date = d1.date_input("Ngày gửi", value=now().date())
            sent_time = d2.time_input("Giờ gửi", value=time(9,0), step=900)
            hours = d3.number_input("Chờ follow-up (giờ)", min_value=1, max_value=720, value=48)
            submitted = st.form_submit_button("Lưu báo giá", type="primary")
        if submitted:
            if not all([code.strip(),customer.strip(),pol.strip(),pod.strip()]):
                st.error("Vui lòng nhập mã báo giá, khách hàng, cảng đi và cảng đến.")
            elif email.strip() and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
                st.error("Email không đúng định dạng.")
            else:
                try:
                    add_quote(code.strip(), customer.strip(), contact.strip(), email.strip(),
                              pol.strip(), pod.strip(), cargo.strip(), float(price),
                              datetime.combine(sent_date, sent_time), int(hours))
                    st.success(f"Đã thêm báo giá {code.strip()}. Chuyển sang tab 'Chi tiết & phản hồi' để xử lý.")
                except sqlite3.IntegrityError:
                    st.error("Mã báo giá đã tồn tại. Hãy chọn mã khác.")
    with tab_detail:
        latest = all_quotes()
        codes = [q["id"] for q in latest]
        if not codes:
            st.info("Chưa có báo giá.")
            return
        chosen = st.selectbox("Chọn báo giá", codes, format_func=lambda c: quote_selector_label(next(q for q in latest if q["id"] == c)))
        q = one_quote(chosen)
        i1,i2,i3 = st.columns(3)
        i1.metric("Trạng thái", status_display(q))
        i2.metric("Hạn follow-up", human_dt(iso(due_at(q))) if q["status"] in OPEN_STATUSES else "Đã có phản hồi")
        i3.metric("Giá báo", f'{q["quoted_usd"]:,.0f} USD')
        st.caption(f"Liên hệ: {q['contact'] or '—'} · Email: {q['email'] or '—'} · Tuyến: {q['origin']} → {q['destination']}")
        part1, part2 = st.columns([1.25,1], gap="large")
        with part1:
            with st.container(border=True):
                st.subheader("Phân loại phản hồi khách hàng")
                with st.form(f"reply_form_{chosen}"):
                    message = st.text_area("Nội dung phản hồi từ khách", value=q["reply_text"],
                                           height=150, placeholder="Ví dụ: Could you offer a lower freight rate?")
                    status_option = st.selectbox("Trạng thái sau khi Sales xác nhận",
                        ["Theo gợi ý hệ thống", "Đã phản hồi", "Đã booking", "Từ chối"])
                    submit_reply = st.form_submit_button("Phân loại & lưu phản hồi", type="primary")
                if submit_reply:
                    if not message.strip():
                        st.error("Chưa có nội dung phản hồi để phân loại.")
                    else:
                        override = None if status_option == "Theo gợi ý hệ thống" else status_option
                        category, suggestion, final_status = save_reply(chosen, message, override)
                        st.success(f"Đã lưu: {category} · {final_status}")
                        st.info(f"**Đề xuất cho Sales:** {suggestion}")
                if q["reply_text"]:
                    st.markdown(f"**Phản hồi gần nhất:** {q['reply_category'] or 'Chưa phân loại'}")
                    st.info(q["recommendation"] or "Sales cần kiểm tra thêm.")
                st.caption("Phân loại dựa trên từ khóa ở chế độ offline. Đây không phải mô hình AI học máy; Sales phải kiểm tra trước khi sử dụng.")
        with part2:
            with st.container(border=True):
                st.subheader("Thao tác Sales")
                if q["status"] in OPEN_STATUSES:
                    note = st.text_input("Ghi chú follow-up", key=f"followup_note_{chosen}",
                                         placeholder="Đã gọi điện / nhắn email, khách chưa trả lời…")
                    if st.button("✅ Ghi nhận đã follow-up", key=f"btn_fu_{chosen}"):
                        follow_up_done(chosen, note)
                        st.success("Đã cập nhật thời điểm liên hệ và kỳ nhắc mới.")
                        st.rerun()
                st.markdown("**Tạo công việc cho báo giá**")
                if st.button("➕ Tạo task follow-up", key=f"add_task_{chosen}"):
                    add_task(chosen, "Liên hệ khách hàng sau báo giá", now() + timedelta(hours=24), "Cao")
                    st.success("Đã tạo task. Xem ở mục Tasks.")
                st.markdown("**Lịch sử trao đổi**")
                events = get_history(chosen)
                if events:
                    event_df = pd.DataFrame([{"Thời gian": human_dt(x["created_at"]),
                                              "Hoạt động": x["action"], "Ghi chú": x["detail"]} for x in events])
                    st.dataframe(event_df, hide_index=True, use_container_width=True, height=250)


def page_tasks() -> None:
    page_heading("Follow-up workflow / Tasks", "Tasks & nhắc lịch follow-up", "Ưu tiên báo giá chưa phản hồi, tạo công việc và theo dõi tiến độ Sales.")
    quotes = all_quotes()
    tasks = all_tasks()
    pending = [t for t in tasks if t["status"] == "Cần làm"]
    overdue_tasks = [t for t in pending if read_dt(t["due_at"]) <= now()]
    c1,c2,c3 = st.columns(3)
    c1.metric("Công việc chưa hoàn thành", len(pending))
    c2.metric("Task quá hạn", len(overdue_tasks))
    c3.metric("Báo giá cần follow-up", sum(is_overdue(q) for q in quotes))
    t1,t2 = st.tabs(["📌 Danh sách công việc", "➕ Thêm task"])
    with t1:
        scope = st.radio("Hiển thị", ["Cần làm", "Tất cả", "Hoàn thành"], horizontal=True)
        filtered = [t for t in tasks if (scope == "Tất cả" or t["status"] == scope)]
        df = pd.DataFrame([{
            "ID": t["id"], "Mã báo giá": t["quote_id"], "Khách hàng": t["customer"],
            "Công việc": t["title"], "Ưu tiên": t["priority"],
            "Hạn xử lý": human_dt(t["due_at"]), "Trạng thái": t["status"],
        } for t in filtered])
        if not df.empty:
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.info("Không có công việc trong bộ lọc này.")
        if pending:
            opts = {t["id"]:f"#{t['id']} · {t['quote_id']} · {t['title']}" for t in pending}
            selected = st.selectbox("Chọn công việc cần hoàn thành", list(opts), format_func=lambda v: opts[v])
            if st.button("✔ Đánh dấu hoàn thành", type="primary"):
                finish_task(int(selected))
                st.success("Đã hoàn thành task và ghi lịch sử follow-up.")
                st.rerun()
        st.divider()
        st.subheader("Các báo giá đang quá hạn nhưng chưa phản hồi")
        late_quotes = sorted([q for q in quotes if is_overdue(q)],key=due_at)
        if late_quotes:
            st.dataframe(quote_table(late_quotes), hide_index=True, use_container_width=True)
            code = st.selectbox("Chọn báo giá tạo việc nhắc", [q["id"] for q in late_quotes])
            if st.button("Tạo task ưu tiên cao"):
                add_task(code, "Follow-up báo giá đã quá hạn", now() + timedelta(hours=4), "Cao")
                st.success("Đã tạo task ưu tiên cao.")
                st.rerun()
        else:
            st.success("Không có báo giá quá hạn.")
    with t2:
        with st.form("new_task"):
            chosen = st.selectbox("Báo giá", [q["id"] for q in quotes],
                                  format_func=lambda c: quote_selector_label(next(q for q in quotes if q["id"] == c)))
            title = st.text_input("Tên công việc", value="Liên hệ khách hàng sau báo giá")
            pr = st.selectbox("Mức ưu tiên", ["Cao", "Trung bình", "Thấp"])
            col1,col2 = st.columns(2)
            due_date = col1.date_input("Ngày đến hạn", value=now().date() + timedelta(days=1))
            due_time = col2.time_input("Giờ đến hạn", value=time(9,0),step=900)
            note = st.text_area("Ghi chú")
            create = st.form_submit_button("Tạo công việc", type="primary")
        if create:
            if title.strip():
                add_task(chosen,title.strip(),datetime.combine(due_date,due_time),pr,note.strip())
                st.success("Đã tạo công việc.")
            else:
                st.error("Cần nhập tên công việc.")
    st.caption("Bản demo kiểm tra hạn khi mở hoặc tải lại ứng dụng, không gửi thông báo nền hoặc email tự động.")


def page_email() -> None:
    page_heading("Sales communication / Drafts", "Mẫu email follow-up", "Tạo email nháp theo tình huống, chỉnh sửa và lưu lịch sử trước khi gửi thủ công.")
    quotes = all_quotes()
    if not quotes:
        st.info("Cần tạo báo giá ở Leads trước khi soạn email.")
        return
    labels = {q["id"]: quote_selector_label(q) for q in quotes}
    col1, col2 = st.columns(2)
    chosen = col1.selectbox("Chọn báo giá", list(labels), format_func=lambda c:labels[c])
    situation = col2.selectbox("Tình huống", ["Nhắc nhẹ – chưa phản hồi", "Giá cước và phụ phí",
                    "Lịch tàu và thời gian vận chuyển", "Điều kiện dịch vụ", "Xác nhận booking", "Khách hàng từ chối"])
    tone,language = st.columns(2)
    tone_value = tone.radio("Giọng văn", ["Chuyên nghiệp", "Thân thiện"], horizontal=True)
    language_value = language.radio("Ngôn ngữ", ["Tiếng Việt", "English"],horizontal=True)
    extra = st.text_area("Thông tin bổ sung (không bắt buộc)", height=90,
                         placeholder="Ví dụ: Nhờ khách xác nhận nhu cầu và thời gian dự kiến booking.")
    if st.button("✨ Tạo email nháp", type="primary"):
        st.session_state["draft_editor"] = draft_email(one_quote(chosen),situation,tone_value,language_value,extra)
        st.session_state["draft_owner"] = chosen
    if "draft_editor" not in st.session_state:
        st.session_state["draft_editor"] = draft_email(one_quote(chosen),situation,tone_value,language_value,extra)
        st.session_state["draft_owner"] = chosen
    st.text_area("Nội dung email nháp – Sales kiểm tra trước khi gửi", key="draft_editor",height=300)
    a,b = st.columns(2)
    a.download_button("⬇️ Tải email nháp (.txt)", st.session_state["draft_editor"].encode("utf-8-sig"),
                      f"email_followup_{st.session_state['draft_owner']}.txt",mime="text/plain",use_container_width=True)
    if b.button("💾 Lưu bản nháp vào lịch sử", use_container_width=True):
        store_draft(st.session_state["draft_owner"], st.session_state["draft_editor"])
        st.success(f"Đã lưu bản nháp vào lịch sử báo giá {st.session_state['draft_owner']}.")
    st.info("Email chỉ được tạo dưới dạng bản nháp. App KHÔNG tự gửi email; Sales cần kiểm tra giá, lịch tàu, điều khoản trước khi gửi qua email công ty.")


with st.sidebar:
    st.markdown("""
    <div class="brand-box"><div class="brand-symbol">U&I</div>
    <div><div class="brand-title">U&I Logistics</div>
    <div class="brand-sub">Sales Intelligence · Academic Demo</div></div></div>
    <div class="section-caption">KHÔNG GIAN LÀM VIỆC</div>
    """, unsafe_allow_html=True)
    menu = st.radio("Điều hướng", ["📊 Dashboard", "👥 Leads", "✅ Tasks", "✉️ Email nháp"],
                    label_visibility="collapsed")
    st.divider()
    count = metrics(all_quotes())
    st.markdown(f'<span class="info-pill">🔴 {count["late"]} báo giá quá hạn</span>',unsafe_allow_html=True)
    st.write("")
    st.caption("Prototype dành cho học tập · Không phải phần mềm chính thức của U&I Logistics.")
    st.caption("🔐 Dữ liệu mẫu giả lập, được lưu trong SQLite trên máy/chủ chạy ứng dụng.")

if menu == "📊 Dashboard":
    page_dashboard()
elif menu == "👥 Leads":
    page_leads()
elif menu == "✅ Tasks":
    page_tasks()
else:
    page_email()
