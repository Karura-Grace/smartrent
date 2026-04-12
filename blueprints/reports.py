import io
from flask import send_file, Blueprint
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

reports_bp = Blueprint("reports", __name__)

# ── shared helpers ──────────────────────────────────────────────
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


# ── 1. Income Report ────────────────────────────────────────────
@reports_bp.route("/reports/income/pdf")
def income_report_pdf():
    buffer = io.BytesIO()
    doc, story = base_doc(buffer, "Income Report — SmartRent", "Period: January – March 2025")

    # TODO: replace with a real DB query, e.g. Payment.query.all()
    data = [
        ["Month",    "Income",       "Expenses",    "Net",          "Occupancy"],
        ["January",  "KES 138,000",  "KES 12,000",  "KES 126,000",  "80%"],
        ["February", "KES 141,500",  "KES 9,500",   "KES 132,000",  "82%"],
        ["March",    "KES 142,000",  "KES 18,500",  "KES 123,500",  "83%"],
    ]
    story.append(styled_table(data))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name="income-report-2025.pdf",
                     mimetype="application/pdf")


# ── 2. Expense Report ───────────────────────────────────────────
@reports_bp.route("/reports/expenses/pdf")
def expense_report_pdf():
    buffer = io.BytesIO()
    doc, story = base_doc(buffer, "Expense Report — SmartRent", "Period: January – March 2025")

    # TODO: replace with real expense records
    data = [
        ["Month",    "Category",     "Description",          "Amount"],
        ["January",  "Maintenance",  "Plumbing repairs",     "KES 7,000"],
        ["January",  "Operational",  "Security guard",       "KES 5,000"],
        ["February", "Maintenance",  "Painting",             "KES 9,500"],
        ["March",    "Maintenance",  "Electrical repairs",   "KES 11,000"],
        ["March",    "Operational",  "Cleaning / security",  "KES 7,500"],
    ]
    story.append(styled_table(data))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name="expense-report-2025.pdf",
                     mimetype="application/pdf")


# ── 3. Occupancy Report ─────────────────────────────────────────
@reports_bp.route("/reports/occupancy/pdf")
def occupancy_report_pdf():
    buffer = io.BytesIO()
    doc, story = base_doc(buffer, "Occupancy Report — SmartRent", "As at March 2025")

    # TODO: replace with real property/unit data
    data = [
        ["Property",      "Total Units", "Occupied", "Vacant", "Occupancy Rate", "Collected"],
        ["Sunset Apts",   "10",          "8",         "2",      "80%",            "KES 68,000"],
        ["Sunrise Apts",  "6",           "6",         "0",      "100%",           "KES 52,000"],
        ["Greenview",     "6",           "4",         "2",      "67%",            "KES 22,000"],
    ]
    story.append(styled_table(data))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name="occupancy-report-2025.pdf",
                     mimetype="application/pdf")


# ── 4. Arrears Report ───────────────────────────────────────────
@reports_bp.route("/reports/arrears/pdf")
def arrears_report_pdf():
    buffer = io.BytesIO()
    doc, story = base_doc(buffer, "Arrears Report — SmartRent", "Outstanding balances as at March 2025")

    # TODO: replace with real tenant/arrears data
    data = [
        ["Tenant",         "Property",     "Unit", "Amount Owed",  "Months Overdue"],
        ["John Kamau",     "Greenview",    "G3",   "KES 12,000",   "2"],
        ["Amina Hassan",   "Sunset Apts",  "S7",   "KES 8,000",    "1"],
        ["Peter Otieno",   "Greenview",    "G5",   "KES 16,500",   "3"],
    ]
    story.append(styled_table(data))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name="arrears-report-2025.pdf",
                     mimetype="application/pdf")