import io
import csv
from datetime import date
from flask import send_file, Blueprint, session, abort, request
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from helpers import login_required
from extensions import get_conn_and_cursor

reports_bp = Blueprint("reports", __name__)

# -- shared helpers ----------------------------------------------
TEAL   = colors.HexColor("#0f766e")
TEAL_L = colors.HexColor("#f0fdfa")
STYLES = getSampleStyleSheet()

def base_doc(buffer, title_text, subtitle_text):
    """Returns a built story list with a title and subtitle already added."""
    doc   = SimpleDocTemplate(buffer, pagesize=A4,
                              leftMargin=2*cm, rightMargin=2*cm,
                              topMargin=2*cm,  bottomMargin=2*cm)
    story = []
    story.append(Paragraph(title_text,    STYLES["Title"]))
    story.append(Paragraph(subtitle_text, STYLES["Normal"]))
    story.append(Spacer(1, 0.5*cm))
    return doc, story

def styled_table(data):
    """Applies SmartRent green header style to a Table."""
    col_count = len(data[0])
    col_width  = 15 * cm / col_count
    t = Table(data, colWidths=[col_width] * col_count)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TEAL),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  10),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, TEAL_L]),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _scope_clause_and_params():
    """
    Returns (where_sql, params) for scoping queries to the current session user.

    Supports landlord and agent roles. Others are forbidden.
    """
    role = (session.get("role") or "").lower()
    user_id = session.get("user_id")
    if not user_id or role not in {"landlord", "agent"}:
        abort(403)

    if role == "agent":
        return "p.agent_id = %s", (user_id,)
    return "p.landlord_id = %s", (user_id,)


def _month_window(year: int, month: int):
    """Return (start_date, next_month_start_date) for SQL params."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def _money(val):
    try:
        return float(val or 0)
    except Exception:
        return 0.0


def _get_income_expense_monthly(year: int, months: list[int]):
    where_sql, where_params = _scope_clause_and_params()
    conn, cur, should_close = get_conn_and_cursor()
    try:
        rows = []
        for m in months:
            start, end = _month_window(year, m)

            cur.execute(
                f"""
                SELECT COALESCE(SUM(CASE WHEN LOWER(pay.status)='paid' THEN pay.Amount ELSE 0 END),0) AS income
                FROM payments pay
                JOIN properties p ON p.id = pay.property_id
                WHERE {where_sql}
                  AND pay.paid_on >= %s AND pay.paid_on < %s
                """,
                (*where_params, start, end),
            )
            income = _money((cur.fetchone() or {}).get("income"))

            cur.execute(
                f"""
                SELECT COALESCE(SUM(CASE WHEN LOWER(b.status)='paid' AND LOWER(b.bill_type)!='rent' THEN b.amount ELSE 0 END),0) AS expenses
                FROM bills b
                JOIN tenant t     ON t.id = b.tenant_id
                JOIN properties p ON p.id = t.property_id
                WHERE {where_sql}
                  AND b.created_at >= %s AND b.created_at < %s
                """,
                (*where_params, start, end),
            )
            expenses = _money((cur.fetchone() or {}).get("expenses"))

            rows.append(
                {
                    "year": year,
                    "month": m,
                    "label": date(year, m, 1).strftime("%B"),
                    "income": income,
                    "expenses": expenses,
                    "net": income - expenses,
                }
            )
        return rows
    finally:
        try:
            cur.close()
        finally:
            if should_close:
                conn.close()


def _get_occupancy_by_property(year: int, month: int):
    where_sql, where_params = _scope_clause_and_params()
    start, end = _month_window(year, month)
    conn, cur, should_close = get_conn_and_cursor()
    try:
        cur.execute(
            f"""
            SELECT
                p.name AS property_name,
                COUNT(u.id) AS total_units,
                SUM(CASE WHEN u.status='Occupied' THEN 1 ELSE 0 END) AS occupied,
                SUM(CASE WHEN u.status='Vacant' THEN 1 ELSE 0 END) AS vacant,
                ROUND(
                    (SUM(CASE WHEN u.status='Occupied' THEN 1 ELSE 0 END) / NULLIF(COUNT(u.id),0)) * 100
                ) AS occupancy_pct,
                COALESCE(SUM(CASE WHEN LOWER(pay.status)='paid' THEN pay.Amount ELSE 0 END),0) AS collected
            FROM properties p
            LEFT JOIN units u ON u.property_id = p.id
            LEFT JOIN payments pay
                   ON pay.property_id = p.id
                  AND pay.paid_on >= %s AND pay.paid_on < %s
            WHERE {where_sql}
            GROUP BY p.id, p.name
            ORDER BY p.name
            """,
            (start, end, *where_params),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        try:
            cur.close()
        finally:
            if should_close:
                conn.close()


def _get_arrears(year: int, month: int):
    """
    Arrears: unpaid/partial bills for the given month label (e.g. "May 2026").
    """
    where_sql, where_params = _scope_clause_and_params()
    month_label = date(year, month, 1).strftime("%B %Y")
    conn, cur, should_close = get_conn_and_cursor()
    try:
        cur.execute(
            f"""
            SELECT
                t.name AS tenant_name,
                p.name AS property_name,
                u.unit_number AS unit_number,
                COALESCE(SUM(CASE WHEN LOWER(b.status)!='paid' THEN b.amount_due ELSE 0 END),0) AS amount_owed,
                SUM(CASE WHEN LOWER(b.status)!='paid' THEN 1 ELSE 0 END) AS pending_items
            FROM bills b
            JOIN tenant t     ON t.id = b.tenant_id
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE {where_sql}
              AND b.month = %s
            GROUP BY t.id, t.name, p.name, u.unit_number
            HAVING amount_owed > 0
            ORDER BY amount_owed DESC, t.name
            """,
            (*where_params, month_label),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        try:
            cur.close()
        finally:
            if should_close:
                conn.close()


# -- 1. Income Report --------------------------------------------
@reports_bp.route("/reports/income/pdf")
@login_required
def income_report_pdf():
    year = int(request.args.get("year") or date.today().year)
    months = [int(m) for m in (request.args.get("months") or "1,2,3").split(",") if m.strip().isdigit()]
    months = [m for m in months if 1 <= m <= 12] or [date.today().month]

    buffer = io.BytesIO()
    subtitle = f"Period: {date(year, months[0], 1).strftime('%B')} - {date(year, months[-1], 1).strftime('%B %Y')}"
    doc, story = base_doc(buffer, "Income Report - SmartRent", subtitle)

    monthly = _get_income_expense_monthly(year, months)
    occ_rows = _get_occupancy_by_property(year, months[-1])
    occ_pct = 0
    if occ_rows:
        total_units = sum(int(r.get("total_units") or 0) for r in occ_rows)
        occupied = sum(int(r.get("occupied") or 0) for r in occ_rows)
        occ_pct = round((occupied / total_units) * 100) if total_units else 0

    data = [["Month", "Income", "Expenses", "Net", "Occupancy"]]
    for r in monthly:
        data.append([
            r["label"],
            f"KES {r['income']:,.0f}",
            f"KES {r['expenses']:,.0f}",
            f"KES {r['net']:,.0f}",
            f"{occ_pct}%",
        ])
    story.append(styled_table(data))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=f"income-report-{year}.pdf",
                     mimetype="application/pdf")


# -- 2. Expense Report -------------------------------------------
@reports_bp.route("/reports/expenses/pdf")
@login_required
def expense_report_pdf():
    year = int(request.args.get("year") or date.today().year)
    month = int(request.args.get("month") or date.today().month)
    buffer = io.BytesIO()
    subtitle = f"Month: {date(year, month, 1).strftime('%B %Y')}"
    doc, story = base_doc(buffer, "Expense Report - SmartRent", subtitle)

    # Treat non-rent paid bills as expenses ledger entries (DB-backed).
    where_sql, where_params = _scope_clause_and_params()
    start, end = _month_window(year, month)
    conn, cur, should_close = get_conn_and_cursor()
    try:
        cur.execute(
            f"""
            SELECT
                DATE_FORMAT(b.created_at, '%%Y-%%m') AS ym,
                b.bill_type AS category,
                CONCAT('Bill #', b.id) AS description,
                b.amount AS amount
            FROM bills b
            JOIN tenant t     ON t.id = b.tenant_id
            JOIN properties p ON p.id = t.property_id
            WHERE {where_sql}
              AND b.created_at >= %s AND b.created_at < %s
              AND LOWER(b.status)='paid'
              AND LOWER(b.bill_type)!='rent'
            ORDER BY b.created_at DESC, b.id DESC
            """,
            (*where_params, start, end),
        )
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        if should_close:
            conn.close()

    data = [["Month", "Category", "Description", "Amount"]]
    if not rows:
        data.append([date(year, month, 1).strftime("%B"), "-", "No expense records found", "KES 0"])
    else:
        for r in rows[:200]:
            data.append([
                date(year, month, 1).strftime("%B"),
                r.get("category") or "-",
                r.get("description") or "-",
                f"KES {_money(r.get('amount')):,.0f}",
            ])
    story.append(styled_table(data))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=f"expense-report-{year}-{month:02d}.pdf",
                     mimetype="application/pdf")


# -- 3. Occupancy Report -----------------------------------------
@reports_bp.route("/reports/occupancy/pdf")
@login_required
def occupancy_report_pdf():
    year = int(request.args.get("year") or date.today().year)
    month = int(request.args.get("month") or date.today().month)
    buffer = io.BytesIO()
    subtitle = f"As at {date(year, month, 1).strftime('%B %Y')}"
    doc, story = base_doc(buffer, "Occupancy Report - SmartRent", subtitle)

    rows = _get_occupancy_by_property(year, month)
    data = [["Property", "Total Units", "Occupied", "Vacant", "Occupancy Rate", "Collected"]]
    if not rows:
        data.append(["-", "0", "0", "0", "0%", "KES 0"])
    else:
        for r in rows:
            data.append([
                r.get("property_name") or "-",
                str(int(r.get("total_units") or 0)),
                str(int(r.get("occupied") or 0)),
                str(int(r.get("vacant") or 0)),
                f"{int(r.get('occupancy_pct') or 0)}%",
                f"KES {_money(r.get('collected')):,.0f}",
            ])
    story.append(styled_table(data))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=f"occupancy-report-{year}-{month:02d}.pdf",
                     mimetype="application/pdf")


# -- 4. Arrears Report -------------------------------------------
@reports_bp.route("/reports/arrears/pdf")
@login_required
def arrears_report_pdf():
    year = int(request.args.get("year") or date.today().year)
    month = int(request.args.get("month") or date.today().month)
    buffer = io.BytesIO()
    subtitle = f"Outstanding balances for {date(year, month, 1).strftime('%B %Y')}"
    doc, story = base_doc(buffer, "Arrears Report - SmartRent", subtitle)

    rows = _get_arrears(year, month)
    data = [["Tenant", "Property", "Unit", "Amount Owed", "Pending Items"]]
    if not rows:
        data.append(["-", "-", "-", "KES 0", "0"])
    else:
        for r in rows[:250]:
            data.append([
                r.get("tenant_name") or "-",
                r.get("property_name") or "-",
                r.get("unit_number") or "-",
                f"KES {_money(r.get('amount_owed')):,.0f}",
                str(int(r.get("pending_items") or 0)),
            ])
    story.append(styled_table(data))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=f"arrears-report-{year}-{month:02d}.pdf",
                     mimetype="application/pdf")


@reports_bp.route("/reports/income/csv")
@login_required
def income_report_csv():
    year = int(request.args.get("year") or date.today().year)
    months = [int(m) for m in (request.args.get("months") or "").split(",") if m.strip().isdigit()]
    months = [m for m in months if 1 <= m <= 12] or list(range(1, 13))
    monthly = _get_income_expense_monthly(year, months)

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Year", "Month", "Income", "Expenses", "Net"])
    for r in monthly:
        w.writerow([r["year"], r["month"], f"{r['income']:.2f}", f"{r['expenses']:.2f}", f"{r['net']:.2f}"])

    mem = io.BytesIO(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f"income-report-{year}.csv", mimetype="text/csv")


@reports_bp.route("/reports/occupancy/csv")
@login_required
def occupancy_report_csv():
    year = int(request.args.get("year") or date.today().year)
    month = int(request.args.get("month") or date.today().month)
    rows = _get_occupancy_by_property(year, month)

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Property", "Total Units", "Occupied", "Vacant", "Occupancy %", "Collected"])
    for r in rows:
        w.writerow([
            r.get("property_name") or "",
            int(r.get("total_units") or 0),
            int(r.get("occupied") or 0),
            int(r.get("vacant") or 0),
            int(r.get("occupancy_pct") or 0),
            f"{_money(r.get('collected')):.2f}",
        ])

    mem = io.BytesIO(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f"occupancy-report-{year}-{month:02d}.csv", mimetype="text/csv")


@reports_bp.route("/reports/arrears/csv")
@login_required
def arrears_report_csv():
    year = int(request.args.get("year") or date.today().year)
    month = int(request.args.get("month") or date.today().month)
    rows = _get_arrears(year, month)

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Tenant", "Property", "Unit", "Amount Owed", "Pending Items"])
    for r in rows:
        w.writerow([
            r.get("tenant_name") or "",
            r.get("property_name") or "",
            r.get("unit_number") or "",
            f"{_money(r.get('amount_owed')):.2f}",
            int(r.get("pending_items") or 0),
        ])

    mem = io.BytesIO(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f"arrears-report-{year}-{month:02d}.csv", mimetype="text/csv")


@reports_bp.route("/reports/expenses/csv")
@login_required
def expenses_report_csv():
    year = int(request.args.get("year") or date.today().year)
    month = int(request.args.get("month") or date.today().month)

    where_sql, where_params = _scope_clause_and_params()
    start, end = _month_window(year, month)
    conn, cur, should_close = get_conn_and_cursor()
    try:
        cur.execute(
            f"""
            SELECT b.id, b.bill_type AS category, b.amount, b.created_at
            FROM bills b
            JOIN tenant t     ON t.id = b.tenant_id
            JOIN properties p ON p.id = t.property_id
            WHERE {where_sql}
              AND b.created_at >= %s AND b.created_at < %s
              AND LOWER(b.status)='paid'
              AND LOWER(b.bill_type)!='rent'
            ORDER BY b.created_at DESC, b.id DESC
            """,
            (*where_params, start, end),
        )
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        if should_close:
            conn.close()

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Bill ID", "Category", "Amount", "Created At"])
    for r in rows:
        w.writerow([r.get("id"), r.get("category") or "", f"{_money(r.get('amount')):.2f}", r.get("created_at")])

    mem = io.BytesIO(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f"expense-report-{year}-{month:02d}.csv", mimetype="text/csv")
    
