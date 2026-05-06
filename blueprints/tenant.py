from datetime import date, datetime
from services.tenant_service import get_dashboard_stats

import MySQLdb
from flask import Blueprint, flash, redirect, render_template, request, session, url_for, make_response

from extensions import get_db_connection, mysql, record_transaction
from helpers import login_required


tenant_bp = Blueprint("tenant", __name__)


def _get_conn_and_cursor():
    try:
        if mysql.connection is not None:
            conn = mysql.connection
            cur = conn.cursor(MySQLdb.cursors.DictCursor)
            return conn, cur, False
    except Exception:
        pass

    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    return conn, cur, True


def _current_month_label():
    return date.today().strftime("%B %Y")

def _get_tenant_profile(cur, tenant_id):
    """
    Directly fetches a tenant profile using the Tenant ID.
    """
    # 1. Fetch profile using the tenant's primary key
    cur.execute(
        """
        SELECT 
            t.*, 
            u.unit_number, 
            u.property_id, 
            p.name AS property_name, 
            p.address 
        FROM tenant t
        LEFT JOIN units u ON t.unit_id = u.id 
        LEFT JOIN properties p ON u.property_id = p.id 
        WHERE t.id = %s 
        LIMIT 1
        """, 
        (tenant_id,)
    )
    
    tenant = cur.fetchone()
    
    if not tenant:
        print(f"No tenant found with ID: {tenant_id}")
        return None

    return tenant

def _resolve_tenant_profile(cur, session_user_id):
    """
    Resolves the current tenant row from the session id.

    Historically, `session['user_id']` has been used inconsistently:
    - sometimes it contains `tenant.id` (tenant_id)
    - sometimes it contains `users.id` (user_id)

    This helper supports both by trying tenant.id first, then tenant.user_id.
    """
    if not session_user_id:
        return None

    # 1) Treat session id as tenant_id
    tenant = _get_tenant_profile(cur, session_user_id)
    if tenant:
        return tenant

    # 2) Treat session id as users.id (tenant.user_id)
    cur.execute(
        """
        SELECT id
        FROM tenant
        WHERE user_id = %s
        LIMIT 1
        """,
        (session_user_id,),
    )
    row = cur.fetchone() or {}
    tenant_id = row.get("id")
    if not tenant_id:
        return None
    return _get_tenant_profile(cur, tenant_id)


def _ensure_monthly_rent_bill(conn, tenant_id, rent_amount, month_label=None, due_date=None):
    if not tenant_id:
        return
    try:
        rent_amount = float(rent_amount or 0)
    except Exception:
        return
    if rent_amount <= 0:
        return

    month_label = (month_label or "").strip() or _current_month_label()

    if due_date is None:
        today = date.today()
        try:
            due_date = today.replace(day=5)
        except Exception:
            due_date = today
        if due_date < today:
            due_date = today

    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute(
            """
            SELECT id
            FROM bills
            WHERE tenant_id = %s
              AND LOWER(bill_type) = 'rent'
              AND month = %s
            LIMIT 1
            """,
            (tenant_id, month_label),
        )
        if cur.fetchone():
            return

        cur.execute(
            """
            INSERT INTO bills
                (tenant_id, bill_type, amount, amount_due, due_date, status, month, created_at)
            VALUES (%s, 'Rent', %s, %s, %s, 'Pending', %s, NOW())
            """,
            (tenant_id, rent_amount, rent_amount, due_date, month_label),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        cur.close()


def tenant_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        session_user_id = session.get("user_id")
        if not session_user_id:
            flash("Please login first", "error")
            return redirect(url_for("landing"))

        if (session.get("role") or "").lower() != "tenant":
            flash("Unauthorized access", "error")
            return redirect(url_for("landing"))

        conn, cur, should_close = _get_conn_and_cursor()
        try:
            tenant = _resolve_tenant_profile(cur, session_user_id)
            if not tenant:
                flash("Tenant profile not found. Contact administrator.", "error")
                return redirect(url_for("landing"))
        finally:
            cur.close()
            if should_close:
                conn.close()

        return f(*args, **kwargs)

    return decorated

@tenant_bp.route("/tenant-dashboard")
@login_required
@tenant_required
def tenant_dashboard():
    user_id = session["user_id"]
    conn, cur, should_close = _get_conn_and_cursor()

    try:
        tenant_info = _resolve_tenant_profile(cur, user_id) or {}
        tenant_id = tenant_info.get("id")
        if not tenant_id:
            flash("Tenant profile not found. Contact administrator.", "error")
            return redirect(url_for("landing"))

        #  GET STATS FROM SERVICE
        stats = get_dashboard_stats(cur, tenant_info, tenant_id)

        # recent payments (for activity)
        cur.execute("""
            SELECT Amount AS amount, status, paid_on AS date, method, month
            FROM payments
            WHERE tenant_id = %s
            ORDER BY paid_on DESC
            LIMIT 5
        """, (tenant_id,))

        activity_items = []
        for row in cur.fetchall():
            pay = dict(row)
            activity_items.append({
                "title": pay.get("month") or "Payment",
                "amount": f"KES {float(pay.get('amount') or 0):,.0f}",
                "status": pay.get("status"),
                "date": str(pay.get("date"))[:10] if pay.get("date") else "-",
                "badge_class": "b-green" if (pay.get("status") or "").lower() == "paid" else "b-orange"
            })

        return render_template(
            "tenantdashboard.html",
            user=session,
            tenant_info=tenant_info,

            # PASS STATS
            stats=stats,

            # other data
            tenant_unit=tenant_info.get("unit_number"),
            property_name=tenant_info.get("property_name"),
            lease_status=tenant_info.get("status") or "Active",
            period_label=_current_month_label(),
            activity_items=activity_items
        )

    finally:
        cur.close()
        if should_close:
            conn.close()


@tenant_bp.route("/payments")
@login_required
@tenant_required
def payments():
    user_id = session["user_id"]
    conn, cur, should_close = _get_conn_and_cursor()
    try:
        tenant_info = _resolve_tenant_profile(cur, user_id) or {}
        tenant_id = tenant_info.get("id")
        if not tenant_id:
            flash("Tenant profile not found. Contact administrator.", "error")
            return redirect(url_for("landing"))

        rent_amount = tenant_info.get("amount") or 0
        if (not rent_amount) and tenant_info.get("unit_id"):
            cur.execute("SELECT rent FROM units WHERE id = %s LIMIT 1", (tenant_info.get("unit_id"),))
            rent_amount = (cur.fetchone() or {}).get("rent") or 0
        _ensure_monthly_rent_bill(conn, tenant_id, rent_amount, month_label=_current_month_label())

        cur.execute(
            """
            SELECT id, bill_type, amount, due_date, status, created_at
            FROM bills
            WHERE tenant_id = %s
            ORDER BY due_date ASC, created_at DESC
            """,
            (tenant_id,),
        )
        bills = [dict(r) for r in cur.fetchall()]

        active_bills = []
        rent_due_amount = 0
        electricity_due_amount = 0
        water_due_amount = 0
        pending_bills_count = 0
        next_due_date = None

        for bill in bills:
            status = (bill.get("status") or "Unpaid").strip().title()
            is_paid = status.lower() == "paid"
            due_date = bill.get("due_date")
            overdue = False
            if due_date and isinstance(due_date, str):
                try:
                    due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
                except Exception:
                    due_date = None
            if due_date and due_date < date.today() and not is_paid:
                overdue = True

            if not is_paid:
                pending_bills_count += 1
                bt = (bill.get("bill_type") or "").strip().lower()
                if bt == "rent":
                    rent_due_amount += float(bill.get("amount") or 0)
                elif bt == "electricity":
                    electricity_due_amount += float(bill.get("amount") or 0)
                elif bt == "water":
                    water_due_amount += float(bill.get("amount") or 0)
                if due_date and (next_due_date is None or due_date < next_due_date):
                    next_due_date = due_date

            active_bills.append(
                {
                    "id": bill.get("id"),
                    "name": bill.get("bill_type") or "Bill",
                    "data_name": bill.get("bill_type") or "Bill",
                    "amount": int(float(bill.get("amount") or 0)),
                    "amount_display": f"KES {int(float(bill.get('amount') or 0)):,.0f}",
                    "due": str(due_date) if due_date else "No due date",
                    "period": bill.get("created_at").strftime("%b %Y") if bill.get("created_at") else "",
                    "status": status,
                    "status_class": "b-green" if is_paid else ("b-red" if overdue else "b-orange"),
                    "selected": False,
                }
            )

        cur.execute(
            """
            SELECT id, Amount AS amount, status, paid_on AS date, method, reference, month
            FROM payments
            WHERE tenant_id = %s
            ORDER BY paid_on DESC
            """,
            (tenant_id,),
        )
        payment_history = []
        last_payment_amount = 0
        payments_made = 0
        for row in cur.fetchall():
            pay = dict(row)
            status = (pay.get("status") or "Unpaid").strip().title()
            if not last_payment_amount and status.lower() == "paid":
                last_payment_amount = float(pay.get("amount") or 0)
            if status.lower() == "paid":
                payments_made += 1
            payment_history.append(
                {
                    "id": pay.get("id"),
                    "date": str(pay.get("date"))[:10] if pay.get("date") else "-",
                    "description": pay.get("month") or "Rent Payment",
                    "method": pay.get("method") or "Unknown",
                    "amount": f"KES {float(pay.get('amount') or 0):,.2f}",
                    "status": status,
                    "status_class": "b-green"
                    if status.lower() == "paid"
                    else "b-orange"
                    if status.lower() == "pending"
                    else "b-red",
                    "reference": pay.get("reference") or "-",
                }
            )

        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM maintenance_requests
            WHERE tenant_id = %s AND LOWER(status) IN ('open', 'pending', 'in progress')
            """,
            (tenant_id,),
        )
        active_requests = int((cur.fetchone() or {}).get("total") or 0)

        tenant_unit = tenant_info.get("unit_number") or tenant_info.get("unit") or "-"
        property_name = tenant_info.get("property_name") or "-"
        next_due_date_str = str(next_due_date) if next_due_date else "N/A"

        return render_template(
            "payments.html",
            user=session,
            tenant_info=tenant_info,
            active_bills=active_bills,
            payment_history=payment_history,
            rent_due_amount=rent_due_amount,
            electricity_due_amount=electricity_due_amount,
            water_due_amount=water_due_amount,
            last_payment_amount=last_payment_amount,
            paybill_account=tenant_unit,
            phone_reference=tenant_unit,
            tenant_unit=tenant_unit,
            property_name=property_name,
            period_label=_current_month_label(),
            lease_status=tenant_info.get("status") or "Active",
            next_due_date=next_due_date_str,
            monthly_rent_due=f"KES {rent_due_amount:,.2f}",
            pending_bills_count=pending_bills_count,
            payments_made=payments_made,
            active_requests=active_requests,
            activity_items=payment_history[:5],
        )
    finally:
        cur.close()
        if should_close:
            conn.close()


@tenant_bp.route("/payments/pay", methods=["POST"])
@login_required
@tenant_required
def tenant_pay():
    user_id = session["user_id"]
    bill_ids = request.form.getlist("bill_ids[]") or request.form.getlist("bill_ids")
    method = (request.form.get("method") or "Cash").strip()
    reference = (request.form.get("reference") or "").strip() or f"PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    month = (request.form.get("month") or _current_month_label()).strip()

    if not bill_ids:
        flash("Select at least one bill to pay.", "error")
        return redirect(url_for("tenant.payments"))

    try:
        bill_ids_int = [int(b) for b in bill_ids]
    except ValueError:
        flash("Invalid bill selection.", "error")
        return redirect(url_for("tenant.payments"))

    conn, cur, should_close = _get_conn_and_cursor()
    try:
        tenant = _resolve_tenant_profile(cur, user_id) or {}
        tenant_id = tenant.get("id")
        if not tenant_id:
            flash("Tenant profile not found. Contact administrator.", "error")
            return redirect(url_for("landing"))

        property_id = tenant.get("property_id") or tenant.get("unit_property_id")

        placeholders = ",".join(["%s"] * len(bill_ids_int))
        cur.execute(
            f"""
            SELECT id, amount, due_date, status
            FROM bills
            WHERE tenant_id = %s AND id IN ({placeholders})
            """,
            tuple([tenant_id] + bill_ids_int),
        )
        bills = [dict(r) for r in cur.fetchall()]
        if not bills:
            flash("No bills found for payment.", "error")
            return redirect(url_for("tenant.payments"))

        total_amount = 0
        penalty_amount = 0
        due_date = None

        for bill in bills:
            bill_status = (bill.get("status") or "Unpaid").strip().lower()
            if bill_status == "paid":
                continue
            amount = float(bill.get("amount") or 0)
            total_amount += amount

            bill_due = bill.get("due_date")
            if bill_due and isinstance(bill_due, str):
                try:
                    bill_due = datetime.strptime(bill_due, "%Y-%m-%d").date()
                except Exception:
                    bill_due = None
            if bill_due and bill_due < date.today():
                penalty_amount += round(amount * 0.05, 2)
            if bill_due and (due_date is None or bill_due < due_date):
                due_date = bill_due

        if total_amount <= 0:
            flash("Selected bills are already paid or have no amount.", "error")
            return redirect(url_for("tenant.payments"))

        for bill in bills:
            if (bill.get("status") or "").strip().lower() != "paid":
                cur.execute("UPDATE bills SET status = 'Paid' WHERE id = %s", (bill["id"],))

        cur.execute(
            """
            INSERT INTO payments
                (tenant_id, unit_id, `phone no`, Amount, status,
                 method, reference, paid_on, property_id, month,
                 due_date, penalty_amount, recorded_by)
            VALUES (%s, %s, %s, %s, 'Paid',
                    %s, %s, NOW(), %s, %s,
                    %s, %s, %s)
            """,
            (
                tenant_id,
                tenant.get("unit_id"),
                (tenant.get("phone") or None),
                total_amount,
                method,
                reference,
                property_id,
                month,
                due_date,
                penalty_amount,
                user_id,
            ),
        )
        payment_id = cur.lastrowid
        record_transaction(payment_id, tenant_id, property_id, total_amount, "Paid", method, reference, due_date, date.today(), penalty_amount)

        conn.commit()
        flash("Payment recorded successfully.", "success")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f"Error recording payment: {str(e)}", "error")
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for("tenant.payments"))


@tenant_bp.route("/bills")
@login_required
@tenant_required
def bills():
    user_id = session["user_id"]
    conn, cur, should_close = _get_conn_and_cursor()
    try:
        tenant = _resolve_tenant_profile(cur, user_id) or {}
        tenant_id = tenant.get("id")
        if not tenant_id:
            flash("Tenant profile not found. Contact administrator.", "error")
            return redirect(url_for("landing"))
        
        # Ensure monthly rent bill exists
        rent_amount = tenant.get("amount") or 0
        if (not rent_amount) and tenant.get("unit_id"):
            cur.execute("SELECT rent FROM units WHERE id = %s LIMIT 1", (tenant.get("unit_id"),))
            rent_amount = (cur.fetchone() or {}).get("rent") or 0
        _ensure_monthly_rent_bill(conn, tenant_id, rent_amount, month_label=_current_month_label())
        
        # Fetch all bills for this tenant
        cur.execute(
            """
            SELECT id, bill_type, amount, amount_due, due_date, status, month, created_at
            FROM bills
            WHERE tenant_id = %s
            ORDER BY due_date ASC, created_at DESC
            """,
            (tenant_id,),
        )
        bills = [dict(r) for r in cur.fetchall()]
        
        # --- Format active bills (unpaid) ---
        active_bills = []
        unpaid_count = 0
        outstanding_total = 0
        rent_due_amount = 0
        electricity_due_amount = 0
        water_due_amount = 0
        next_due_date = None
        
        # Track last payment from payment history (not bills)
        last_payment_amount = 0
        
        for bill in bills:
            status = (bill.get("status") or "Unpaid").strip().title()
            is_paid = status.lower() == "paid"
            due_date = bill.get("due_date")
            
            # Parse due date
            if due_date and isinstance(due_date, (date, datetime)):
                due_date_obj = due_date
            elif due_date and isinstance(due_date, str):
                try:
                    due_date_obj = datetime.strptime(due_date, "%Y-%m-%d").date()
                except Exception:
                    due_date_obj = None
            else:
                due_date_obj = None
            
            # Calculate overdue status
            overdue = False
            if due_date_obj and due_date_obj < date.today() and not is_paid:
                overdue = True
            
            # Icon and color mapping based on bill type
            bill_type = (bill.get("bill_type") or "Bill")
            icon_map = {
                "rent": ("home", "ico-blue"),
                "electricity": ("zap", "ico-orange"),
                "water": ("droplets", "ico-blue"),
                "service": ("settings", "ico-purple"),
                "late fee": ("alert-circle", "ico-red"),
                "penalty": ("alert-triangle", "ico-red"),
            }
            icon, icon_bg = icon_map.get(bill_type, ("receipt", "ico-gray"))
            
            # Format amount
            amount = float(bill.get("amount") or 0)
            
            if not is_paid:
                unpaid_count += 1
                outstanding_total += amount
                
                # Track category totals
                if bill_type == "rent":
                    rent_due_amount += amount
                elif bill_type == "electricity":
                    electricity_due_amount += amount
                elif bill_type == "water":
                    water_due_amount += amount
                
                # Track next due date (earliest unpaid bill)
                if due_date_obj and (next_due_date is None or due_date_obj < next_due_date):
                    next_due_date = due_date_obj
            
            # Format period/month display
            month_label = bill.get("month") or ""
            if not month_label and bill.get("created_at"):
                month_label = bill["created_at"].strftime("%B %Y") if isinstance(bill["created_at"], (date, datetime)) else ""
            
            active_bills.append({
                "id": bill.get("id"),
                "name": bill.get("bill_type") or "Bill",
                "data_name": bill.get("bill_type") or "Bill",
                "icon": icon,
                "icon_bg": icon_bg,
                "amount": int(amount),
                "amount_display": f"KES {int(amount):,.0f}",
                "due": due_date_obj.strftime("%b %d, %Y") if due_date_obj else "No due date",
                "period": month_label or _current_month_label(),
                "category": bill.get("bill_type") or "Other",
                "note": f"{'Overdue' if overdue else 'Pending'} payment",
                "status": status,
                "status_class": "b-green" if is_paid else ("b-red" if overdue else "b-orange"),
            })
        
        # --- Fetch payment history ---
        cur.execute(
            """
            SELECT id, Amount AS amount, status, paid_on AS date, method, reference, month
            FROM payments
            WHERE tenant_id = %s
            ORDER BY paid_on DESC
            LIMIT 10
            """,
            (tenant_id,),
        )
        
        bill_history = []
        for row in cur.fetchall():
            pay = dict(row)
            status = (pay.get("status") or "Unpaid").strip().title()
            amount = float(pay.get("amount") or 0)
            
            # Track last payment amount
            if not last_payment_amount and status.lower() == "paid":
                last_payment_amount = amount
            
            pay_date = pay.get("date")
            if pay_date and isinstance(pay_date, (date, datetime)):
                date_str = pay_date.strftime("%Y-%m-%d")
            else:
                date_str = str(pay_date)[:10] if pay_date else "-"
            
            bill_history.append({
                "id": pay.get("id"),
                "date": date_str,
                "name": pay.get("month") or "Payment",
                "period": pay.get("month") or _current_month_label(),
                "amount": f"KES {amount:,.2f}",
                "status": status,
                "method": pay.get("method") or "Unknown",
            })
        
        # Format last payment display
        if last_payment_amount > 0:
            last_payment_display = f"KES {last_payment_amount:,.0f}"
        else:
            last_payment_display = "No payments"
        
        # Format next due date
        next_due_date_str = next_due_date.strftime("%b %d, %Y") if next_due_date else "No upcoming bills"
        
        # Get property info for context
        property_name = tenant.get("property_name") or "Your Property"
        tenant_unit = tenant.get("unit_number") or tenant.get("unit") or "-"
        
        return render_template(
            "bills.html",
            user=session,
            tenant_info=tenant,
            active_bills=active_bills,
            unpaid_count=unpaid_count,
            outstanding_total=f"KES {outstanding_total:,.0f}",
            last_payment_display=last_payment_display,
            next_due_date=next_due_date_str,
            bill_history=bill_history,
            rent_due_amount=f"KES {rent_due_amount:,.0f}",
            electricity_due_amount=f"KES {electricity_due_amount:,.0f}",
            water_due_amount=f"KES {water_due_amount:,.0f}",
            property_name=property_name,
            tenant_unit=tenant_unit,
            period_label=_current_month_label(),
        )
    except Exception as e:
        print(f"Error in bills route: {e}")
        flash(f"Error loading bills: {str(e)}", "error")
        return render_template(
            "bills.html",
            user=session,
            active_bills=[],
            unpaid_count=0,
            outstanding_total="KES 0",
            last_payment_display="No payments",
            next_due_date="No upcoming bills",
            bill_history=[],
            rent_due_amount="KES 0",
            electricity_due_amount="KES 0",
            water_due_amount="KES 0",
            property_name="-",
            tenant_unit="-",
            period_label=_current_month_label(),
        )
    finally:
        cur.close()
        if should_close:
            conn.close()


@tenant_bp.route("/services")
@login_required
@tenant_required
def services():
    user_id = session["user_id"]
    conn, cur, should_close = _get_conn_and_cursor()
    try:
        tenant = _resolve_tenant_profile(cur, user_id) or {}
        tenant_id = tenant.get("id")
        if not tenant_id:
            flash("Tenant profile not found. Contact administrator.", "error")
            return redirect(url_for("landing"))
        cur.execute(
            """
            SELECT id, title, description, priority, status, created_at
            FROM maintenance_requests
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        requests_list = [dict(r) for r in cur.fetchall()]
        return render_template("services.html", user=session, requests=requests_list)
    finally:
        cur.close()
        if should_close:
            conn.close()


@tenant_bp.route("/documents")
@login_required
@tenant_required
def documents():
    """Tenant: documents & receipts area (currently: receipts)."""
    user_id = session["user_id"]
    conn, cur, should_close = _get_conn_and_cursor()
    try:
        tenant = _resolve_tenant_profile(cur, user_id) or {}
        tenant_id = tenant.get("id")
        if not tenant_id:
            flash("Tenant profile not found. Contact administrator.", "error")
            return redirect(url_for("landing"))

        cur.execute(
            """
            SELECT month,
                   MAX(paid_on) AS last_paid_on,
                   SUM(CASE WHEN LOWER(status)='paid' THEN Amount ELSE 0 END) AS total_paid
            FROM payments
            WHERE tenant_id = %s AND month IS NOT NULL AND month != ''
            GROUP BY month
            ORDER BY MAX(paid_on) DESC
            """,
            (tenant_id,),
        )
        receipts = [dict(r) for r in cur.fetchall()]
        return render_template("documents.html", user=session, receipts=receipts)
    finally:
        cur.close()
        if should_close:
            conn.close()


@tenant_bp.route("/receipt")
@login_required
@tenant_required
def tenant_receipt():
    """Tenant: download an HTML receipt for a given month."""
    user_id = session["user_id"]
    month = (request.args.get("month") or "").strip() or date.today().strftime("%B %Y")
    conn, cur, should_close = _get_conn_and_cursor()
    try:
        tenant = _resolve_tenant_profile(cur, user_id)
        if not tenant:
            flash("Tenant profile not found.", "error")
            return redirect(url_for("tenant.documents"))

        tenant_id = tenant.get("id")
        property_id = tenant.get("property_id") or tenant.get("unit_property_id")
        cur.execute(
            """
            SELECT Amount AS amount, status, paid_on, method, reference
            FROM payments
            WHERE tenant_id = %s AND property_id = %s AND month = %s
            ORDER BY paid_on DESC
            LIMIT 1
            """,
            (tenant_id, property_id, month),
        )
        pay = cur.fetchone() or {}
        if not isinstance(pay, dict):
            pay = dict(pay)

        html = render_template(
            "receipt.html",
            doc_type="Receipt",
            month=month,
            tenant=tenant,
            amount=pay.get("amount") if pay.get("amount") is not None else (tenant.get("amount") or 0),
            status=pay.get("status") or "Unpaid",
            paid_on=pay.get("paid_on"),
            method=pay.get("method"),
            reference=pay.get("reference"),
            issued_at=datetime.now(),
        )
        resp = make_response(html)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="Receipt-{tenant_id}-{month.replace(" ", "-")}.html"'
        return resp
    finally:
        cur.close()
        if should_close:
            conn.close()


@tenant_bp.route("/services/submit", methods=["POST"])
@login_required
@tenant_required
def submit_request():
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    priority = request.form.get("priority", "Medium")

    if not title:
        flash("Title is required.", "error")
        return redirect(url_for("tenant.services"))

    user_id = session["user_id"]
    conn, cur, should_close = _get_conn_and_cursor()
    try:
        tenant = _resolve_tenant_profile(cur, user_id) or {}
        tenant_id = tenant.get("id")
        if not tenant_id:
            flash("Tenant profile not found. Contact administrator.", "error")
            return redirect(url_for("landing"))
        unit_id = tenant.get("unit_id")
        if not unit_id:
            flash("Missing unit assignment. Update your rental info in Settings.", "error")
            return redirect(url_for("tenant.services"))
        property_id = tenant.get("property_id") or tenant.get("unit_property_id")
        if not property_id:
            flash("Missing property assignment. Update your rental info in Settings.", "error")
            return redirect(url_for("tenant.services"))

        cur.execute(
            """
            INSERT INTO maintenance_requests
                (tenant_id, unit_id, property_id, title, description, priority, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'Open', NOW())
            """,
            (tenant_id, unit_id, property_id, title, description, priority),
        )
        conn.commit()
        flash("Maintenance request submitted!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error submitting request: {str(e)}", "error")
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for("tenant.services"))


@tenant_bp.route("/notices")
@login_required
@tenant_required
def notices():
    user_id = session["user_id"]
    conn, cur, should_close = _get_conn_and_cursor()
    try:
        tenant = _resolve_tenant_profile(cur, user_id) or {}
        if not tenant.get("id"):
            flash("Tenant profile not found. Contact administrator.", "error")
            return redirect(url_for("landing"))
        property_id = tenant.get("property_id") or tenant.get("unit_property_id")

        notices_list = []
        if property_id:
            cur.execute(
                """
                SELECT message, type, created_at AS sent_at
                FROM notices
                WHERE property_id = %s
                ORDER BY created_at DESC
                """,
                (property_id,),
            )
            notices_list = [dict(r) for r in cur.fetchall()]

        return render_template("notices.html", user=session, notices=notices_list)
    finally:
        cur.close()
        if should_close:
            conn.close()
