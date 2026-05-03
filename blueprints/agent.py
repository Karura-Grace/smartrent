# blueprints/agent.py
import os
from flask import Blueprint, render_template, redirect, session, url_for, flash, request, current_app, make_response
from helpers import login_required, save_property_image, sync_unit_count, serialize_units
from extensions import mysql, get_db_connection, record_transaction
from functools import wraps
import MySQLdb
from datetime import date, timedelta, datetime
from werkzeug.security import generate_password_hash

agent_bp = Blueprint('agent', __name__)

COMMISSION_RATE = 0.05  # 5% agent earning


def get_conn():
    return mysql.connection if mysql.connection is not None else get_db_connection()


def get_cursor():
    conn = get_conn()
    try:
        return conn.cursor(MySQLdb.cursors.DictCursor)
    except Exception:
        return conn.cursor()


def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if (session.get('role') or '').lower() != 'agent':
            flash('Unauthorized access', 'error')
            return redirect(url_for('landing'))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_overdue_count(agent_id):
    """Returns count of pending+overdue payments for this agent's properties."""
    try:
        cur = get_cursor()
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM   payments pay
            JOIN   properties p ON pay.property_id = p.id
            WHERE  p.agent_id = %s AND LOWER(pay.status) IN ('pending', 'overdue')
        """, (agent_id,))
        row = cur.fetchone()
        cur.close()
        if not row:
            return 0
        return int(row.get('cnt') or 0) if isinstance(row, dict) else int(row[0] or 0)
    except Exception:
        return 0


# ─────────────────────────────────────────────
# LANDLORDS (Agent-linked)
# ─────────────────────────────────────────────

@agent_bp.route('/agent/landlords')
@login_required
@agent_required
def agent_landlords():
    agent_id = session['user_id']
    cur = get_cursor()
    try:
        cur.execute("""
            SELECT al.id AS link_id,
                   u.id AS landlord_id,
                   u.first_name,
                   u.last_name,
                   u.email,
                   (SELECT COUNT(*) FROM properties p WHERE p.landlord_id = u.id) AS properties_count
            FROM agent_landlords al
            JOIN users u ON u.id = al.landlord_id
            WHERE al.agent_id = %s AND LOWER(u.role) = 'landlord'
            ORDER BY u.first_name, u.last_name
        """, (agent_id,))
        landlords = []
        for r in cur.fetchall():
            row = dict(r)
            row['full_name'] = (
                f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
                or row.get('email') or 'Landlord'
            )
            landlords.append(row)
    except Exception:
        landlords = []
    finally:
        cur.close()
    return render_template('agent_landlords.html', user=session, landlords=landlords)


@agent_bp.route('/agent/landlords/link', methods=['POST'])
@login_required
@agent_required
def agent_link_landlord():
    agent_id = session['user_id']
    landlord_email = (request.form.get('landlord_email') or '').strip().lower()
    if not landlord_email:
        flash('Enter the landlord email.', 'error')
        return redirect(url_for('agent.agent_landlords'))

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute(
            "SELECT id, first_name, last_name, email, role FROM users WHERE LOWER(email) = %s LIMIT 1",
            (landlord_email,)
        )
        u = cur.fetchone()
        if not u or (u.get('role') or '').lower() != 'landlord':
            flash('No landlord account found with that email.', 'error')
            return redirect(url_for('agent.agent_landlords'))

        cur.execute(
            "INSERT IGNORE INTO agent_landlords (agent_id, landlord_id) VALUES (%s, %s)",
            (agent_id, u['id']),
        )
        conn.commit()
        flash('Landlord linked successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error linking landlord: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_landlords'))


@agent_bp.route('/agent/landlords/create', methods=['POST'])
@login_required
@agent_required
def agent_create_landlord():
    agent_id = session['user_id']
    first_name = (request.form.get('first_name') or '').strip()
    last_name  = (request.form.get('last_name') or '').strip()
    email      = (request.form.get('email') or '').strip().lower()
    password   = (request.form.get('password') or '').strip()

    if not first_name or not last_name or not email or not password:
        flash('First name, last name, email and password are required.', 'error')
        return redirect(url_for('agent.agent_landlords'))

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("SELECT id, role FROM users WHERE LOWER(email) = %s LIMIT 1", (email,))
        existing = cur.fetchone()
        if existing:
            if (existing.get('role') or '').lower() != 'landlord':
                flash('That email exists but is not a landlord account.', 'error')
                return redirect(url_for('agent.agent_landlords'))
            landlord_id = existing['id']
        else:
            # users.name is NOT NULL — set it to full name
            full_name = f"{first_name} {last_name}".strip()
            cur.execute(
                """
                INSERT INTO users (name, first_name, last_name, email, password, role)
                VALUES (%s, %s, %s, %s, %s, 'landlord')
                """,
                (full_name, first_name, last_name, email, generate_password_hash(password)),
            )
            landlord_id = cur.lastrowid

        cur.execute(
            "INSERT IGNORE INTO agent_landlords (agent_id, landlord_id) VALUES (%s, %s)",
            (agent_id, landlord_id),
        )
        conn.commit()
        flash('Landlord saved and linked to your agent account.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error creating landlord: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_landlords'))


@agent_bp.route('/agent/landlords/edit/<int:landlord_id>', methods=['POST'])
@login_required
@agent_required
def agent_edit_landlord(landlord_id):
    agent_id   = session['user_id']
    first_name = (request.form.get('first_name') or '').strip()
    last_name  = (request.form.get('last_name') or '').strip()
    email      = (request.form.get('email') or '').strip().lower()

    if not first_name or not last_name or not email:
        flash('First name, last name, and email are required.', 'error')
        return redirect(url_for('agent.agent_landlords'))

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute(
            "SELECT 1 FROM agent_landlords WHERE agent_id = %s AND landlord_id = %s",
            (agent_id, landlord_id),
        )
        if not cur.fetchone():
            flash('Landlord not found for your account.', 'error')
            return redirect(url_for('agent.agent_landlords'))

        full_name = f"{first_name} {last_name}".strip()
        cur.execute(
            """UPDATE users
               SET name=%s, first_name=%s, last_name=%s, email=%s
               WHERE id=%s AND LOWER(role)='landlord'""",
            (full_name, first_name, last_name, email, landlord_id),
        )
        conn.commit()
        flash('Landlord updated.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating landlord: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_landlords'))


@agent_bp.route('/agent/landlords/unlink/<int:landlord_id>', methods=['POST'])
@login_required
@agent_required
def agent_unlink_landlord(landlord_id):
    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute(
            "DELETE FROM agent_landlords WHERE agent_id = %s AND landlord_id = %s",
            (agent_id, landlord_id),
        )
        conn.commit()
        flash('Landlord unlinked.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error unlinking landlord: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_landlords'))


@agent_bp.route('/agent/landlords/delete/<int:landlord_id>', methods=['POST'])
@login_required
@agent_required
def agent_delete_landlord(landlord_id):
    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute(
            "SELECT 1 FROM agent_landlords WHERE agent_id = %s AND landlord_id = %s",
            (agent_id, landlord_id),
        )
        if not cur.fetchone():
            flash('Landlord not found for your account.', 'error')
            return redirect(url_for('agent.agent_landlords'))

        cur.execute("SELECT COUNT(*) AS total FROM properties WHERE landlord_id = %s", (landlord_id,))
        if int((cur.fetchone() or {}).get('total') or 0) > 0:
            flash('Cannot delete this landlord because they have properties. Unlink instead.', 'error')
            return redirect(url_for('agent.agent_landlords'))

        cur.execute("DELETE FROM agent_landlords WHERE agent_id = %s AND landlord_id = %s", (agent_id, landlord_id))
        cur.execute("DELETE FROM users WHERE id = %s AND LOWER(role) = 'landlord'", (landlord_id,))
        conn.commit()
        flash('Landlord deleted.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting landlord: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_landlords'))


# ─────────────────────────────────────────────
# AGENT DASHBOARD
# ─────────────────────────────────────────────

@agent_bp.route('/agent-dashboard')
@login_required
@agent_required
def agent_dashboard():
    agent_id       = session['user_id']
    selected_month = (request.args.get('month') or '').strip() or date.today().strftime("%B %Y")
    active_tab     = (request.args.get('tab') or 'props').strip().lower()

    cur = get_cursor()

    # Property KPIs
    cur.execute("""
        SELECT p.*,
               COALESCE(uc.unit_count, 0)    AS unit_count,
               COALESCE(uo.occupied_count, 0) AS occupied_count,
               COALESCE(uv.vacant_count, 0)   AS vacant_count
        FROM   properties p
        LEFT JOIN (SELECT property_id, COUNT(*) AS unit_count   FROM units GROUP BY property_id) uc ON uc.property_id = p.id
        LEFT JOIN (SELECT property_id, COUNT(*) AS occupied_count FROM units WHERE status='Occupied' GROUP BY property_id) uo ON uo.property_id = p.id
        LEFT JOIN (SELECT property_id, COUNT(*) AS vacant_count   FROM units WHERE status='Vacant'   GROUP BY property_id) uv ON uv.property_id = p.id
        WHERE p.agent_id = %s
        ORDER BY p.created_at DESC
    """, (agent_id,))
    properties_summary = [dict(r) for r in cur.fetchall()]

    # Recent units (dashboard table)
    cur.execute("""
        SELECT u.id, u.unit_number, u.rent AS rent_amount,
               LOWER(u.status) AS status,
               p.type AS property_type, p.name AS property_name
        FROM units u
        JOIN properties p ON p.id = u.property_id
        WHERE p.agent_id = %s
        ORDER BY u.id DESC
        LIMIT 10
    """, (agent_id,))
    recent_units = [dict(r) for r in cur.fetchall()]

    # Tenants — DB has no `unit` column; use unit_id joined to units.unit_number
    cur.execute("""
        SELECT t.id, t.name, t.email, t.phone,
               u.unit_number,
               p.name AS property_name,
               t.status, t.amount
        FROM   tenants t
        JOIN   properties p ON t.property_id = p.id
        LEFT JOIN units u   ON u.id = t.unit_id
        WHERE  p.agent_id = %s
        ORDER  BY t.name
    """, (agent_id,))
    tenants = [dict(r) for r in cur.fetchall()]

    # Available months
    cur.execute("""
        SELECT DISTINCT pay.month AS month
        FROM payments pay
        JOIN properties p ON p.id = pay.property_id
        WHERE p.agent_id = %s AND pay.month IS NOT NULL AND pay.month != ''
        ORDER BY pay.paid_on DESC
        LIMIT 24
    """, (agent_id,))
    available_months = [r.get('month') for r in cur.fetchall() if (r.get('month') or '').strip()]
    if selected_month not in available_months:
        available_months = [selected_month] + available_months
    seen = set()
    available_months = [m for m in available_months if not (m in seen or seen.add(m))]

    # Month payments — payments.tenant_id links to tenants.id
    cur.execute("""
        SELECT pay.tenant_id,
               pay.Amount AS amount,
               pay.status,
               pay.paid_on
        FROM payments pay
        JOIN properties p ON p.id = pay.property_id
        WHERE p.agent_id = %s AND pay.month = %s
        ORDER BY pay.paid_on DESC
    """, (agent_id, selected_month))
    month_by_tenant = {}
    for r in cur.fetchall():
        tid = r.get('tenant_id')
        if tid is not None and tid not in month_by_tenant:
            month_by_tenant[tid] = dict(r)

    for t in tenants:
        pr = month_by_tenant.get(t.get('id'))
        st = (pr.get('status') if pr else '') or ''
        t['payment_status'] = 'Paid' if st.strip().lower() == 'paid' else 'Unpaid'

    month_payments = []
    for t in tenants:
        pr = month_by_tenant.get(t.get('id')) or {}
        paid_on = pr.get('paid_on')
        month_payments.append({
            'tenant_id':      t.get('id'),
            'tenant_name':    t.get('name'),
            'amount':         float(pr.get('amount') or t.get('amount') or 0),
            'paid_on':        str(paid_on)[:10] if paid_on else None,
            'payment_status': 'Paid' if t.get('payment_status') == 'Paid' else 'Unpaid',
        })

    # Maintenance tickets — join unit_id, then property via units
    cur.execute("""
        SELECT m.id, m.title, m.priority, m.status,
               m.unit_id, p.name AS property_name, m.created_at
        FROM   maintenance_requests m
        JOIN   units u      ON u.id = m.unit_id
        JOIN   properties p ON p.id = u.property_id
        WHERE  p.agent_id = %s
        ORDER  BY FIELD(m.priority,'High','Medium','Low'), m.created_at DESC
        LIMIT  10
    """, (agent_id,))
    tickets = [dict(r) for r in cur.fetchall()]

    # Notices — notices has no `message` column named differently; use message column
    cur.execute("""
        SELECT title, message, type, created_at AS sent_at
        FROM   notices
        WHERE  sender_id = %s
        ORDER  BY created_at DESC
        LIMIT  5
    """, (agent_id,))
    notices = [dict(r) for r in cur.fetchall()]

    # Recent payments — Amount (capital A), join tenants.id = payments.tenant_id
    cur.execute("""
        SELECT t.name AS tenant_name,
               pay.Amount AS amount,
               pay.paid_on AS date,
               pay.status
        FROM   payments pay
        JOIN   tenants t    ON pay.tenant_id   = t.id
        JOIN   properties p ON pay.property_id = p.id
        WHERE  p.agent_id = %s
        ORDER  BY pay.paid_on DESC
        LIMIT  10
    """, (agent_id,))
    recent_payments = [dict(r) for r in cur.fetchall()]
    cur.close()

    total_units      = sum(p['unit_count']     for p in properties_summary)
    occupied_units   = sum(p['occupied_count'] for p in properties_summary)
    occupancy_rate   = round((occupied_units / total_units * 100) if total_units else 0)
    rent_collected   = sum(float(p.get('amount') or 0) for p in recent_payments if p.get('status') == 'Paid')
    rent_outstanding = sum(float(t.get('amount') or 0) for t in tenants if t.get('payment_status') != 'Paid')

    return render_template('agent_dashboard.html',
        user             = session,
        properties       = recent_units,
        tenant           = tenants,
        tickets          = tickets,
        notices          = notices,
        recent_payments  = recent_payments,
        available_months = available_months,
        selected_month   = selected_month,
        month_payments   = month_payments,
        active_tab       = active_tab,
        total_units      = total_units,
        occupancy_rate   = occupancy_rate,
        rent_collected   = round(rent_collected, 2),
        rent_outstanding = round(rent_outstanding, 2),
        pending_overdue  = get_overdue_count(agent_id),
    )


# ─────────────────────────────────────────────
# RECORD PAYMENT
# ─────────────────────────────────────────────

@agent_bp.route('/agent/payments/record', methods=['POST'])
@login_required
@agent_required
def agent_record_payment():
    agent_id   = session['user_id']
    tenant_id  = (request.form.get('tenant_id') or '').strip()
    month      = (request.form.get('month') or '').strip() or date.today().strftime("%B %Y")
    method     = (request.form.get('method') or 'Cash').strip()
    reference  = (request.form.get('reference') or '').strip()
    amount_raw = (request.form.get('amount') or '').strip()

    try:
        tenant_id_int = int(tenant_id)
        amount = float(amount_raw)
    except ValueError:
        flash('Invalid tenant or amount.', 'error')
        return redirect(url_for('agent.agent_dashboard', tab='tenant', month=month))

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        # tenants has no `unit` text column — get unit_number from joined units table
        cur.execute("""
            SELECT t.id, t.name, t.phone, t.unit_id, t.property_id,
                   u.unit_number
            FROM tenants t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE t.id = %s AND p.agent_id = %s
            LIMIT 1
        """, (tenant_id_int, agent_id))
        t = cur.fetchone()
        if not t:
            flash('Tenant not found for your account.', 'error')
            return redirect(url_for('agent.agent_dashboard', tab='tenant', month=month))

        # payments columns: tenant_id, unit_id, Amount, `phone no`, status, method, reference, paid_on, property_id, month, due_date, penalty_amount, recorded_by
        cur.execute("""
            INSERT INTO payments
                (tenant_id, unit_id, `phone no`, Amount, status,
                 method, reference, paid_on, property_id, month,
                 due_date, penalty_amount, recorded_by)
            VALUES (%s, %s, %s, %s, 'Paid',
                    %s, %s, NOW(), %s, %s,
                    NULL, 0, %s)
        """, (
            t['id'], t.get('unit_id'), t.get('phone'), amount,
            method, reference, t.get('property_id'), month,
            agent_id,
        ))
        payment_id = cur.lastrowid
        record_transaction(payment_id, t['id'], t.get('property_id'), amount,
                           'Paid', method, reference, None, date.today(), 0)
        conn.commit()
        flash(f'Payment recorded for {t.get("name")}.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error recording payment: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_dashboard', tab='payments', month=month))


# ─────────────────────────────────────────────
# RECEIPT HELPERS
# ─────────────────────────────────────────────

def _agent_tenant_for_doc(agent_id: int, tenant_id: int):
    cur = get_cursor()
    try:
        cur.execute("""
            SELECT t.id, t.name, t.email, t.phone, t.amount,
                   u.unit_number,
                   p.name AS property_name, p.id AS property_id
            FROM tenants t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE t.id = %s AND p.agent_id = %s
            LIMIT 1
        """, (tenant_id, agent_id))
        return cur.fetchone()
    finally:
        cur.close()


@agent_bp.route('/agent/tenants/<int:tenant_id>/receipt')
@login_required
@agent_required
def agent_tenant_receipt(tenant_id):
    agent_id = session['user_id']
    month    = (request.args.get('month') or '').strip() or date.today().strftime("%B %Y")
    tenant   = _agent_tenant_for_doc(agent_id, tenant_id)
    if not tenant:
        flash('Tenant not found.', 'error')
        return redirect(url_for('agent.agent_dashboard', tab='tenant', month=month))

    cur = get_cursor()
    try:
        cur.execute("""
            SELECT Amount AS amount, status, paid_on, method, reference
            FROM payments
            WHERE tenant_id = %s AND property_id = %s AND month = %s
            ORDER BY paid_on DESC
            LIMIT 1
        """, (tenant_id, tenant.get('property_id'), month))
        pay = cur.fetchone() or {}
    finally:
        cur.close()

    html = render_template('receipt.html',
        doc_type='Receipt', month=month, tenant=tenant,
        amount=pay.get('amount') if pay.get('amount') is not None else (tenant.get('amount') or 0),
        status=pay.get('status') or 'Unpaid',
        paid_on=pay.get('paid_on'), method=pay.get('method'),
        reference=pay.get('reference'), issued_at=datetime.now(),
    )
    resp = make_response(html)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename="Receipt-{tenant_id}-{month.replace(" ", "-")}.html"'
    return resp


# ─────────────────────────────────────────────
# PROPERTIES
# ─────────────────────────────────────────────

@agent_bp.route('/agent/properties')
@login_required
@agent_required
def agent_properties():
    agent_id = session['user_id']
    cur = get_cursor()
    cur.execute("""
        SELECT p.*,
               COALESCE(uc.unit_count, 0)    AS unit_count,
               COALESCE(uo.occupied_count, 0) AS occupied_count
        FROM   properties p
        LEFT JOIN (SELECT property_id, COUNT(*) AS unit_count   FROM units GROUP BY property_id) uc ON uc.property_id = p.id
        LEFT JOIN (SELECT property_id, COUNT(*) AS occupied_count FROM units WHERE status='Occupied' GROUP BY property_id) uo ON uo.property_id = p.id
        WHERE  p.agent_id = %s
        ORDER  BY p.created_at DESC
    """, (agent_id,))
    properties = [dict(r) for r in cur.fetchall()]
    for p in properties:
        p['image'] = p.get('image', '')

    cur.execute("SELECT COUNT(*) AS total FROM properties WHERE agent_id = %s", (agent_id,))
    total_props = (cur.fetchone() or {}).get('total', 0)

    cur.execute("""
        SELECT COUNT(*) AS total FROM units u
        JOIN properties p ON p.id = u.property_id WHERE p.agent_id = %s
    """, (agent_id,))
    total_units = (cur.fetchone() or {}).get('total', 0)

    cur.execute("""
        SELECT COUNT(*) AS total FROM units u
        JOIN properties p ON p.id = u.property_id
        WHERE p.agent_id = %s AND u.status = 'Occupied'
    """, (agent_id,))
    occupied = (cur.fetchone() or {}).get('total', 0)

    cur.execute("""
        SELECT COUNT(*) AS total FROM units u
        JOIN properties p ON p.id = u.property_id
        WHERE p.agent_id = %s AND u.status = 'Vacant'
    """, (agent_id,))
    vacant = (cur.fetchone() or {}).get('total', 0)

    stats = {'total_props': total_props, 'total_units': total_units, 'occupied': occupied, 'vacant': vacant}
    cur.close()
    return render_template('properties.html',
        user=session, properties=properties, stats=stats,
        pending_overdue=get_overdue_count(agent_id),
    )


@agent_bp.route('/agent/properties/add', methods=['POST'])
@login_required
@agent_required
def agent_add_property():
    name        = request.form.get('name', '').strip()
    address     = request.form.get('address', '').strip()
    city        = request.form.get('city', 'Nairobi').strip()
    prop_type   = request.form.get('type', 'Apartments')
    description = request.form.get('description', '').strip()

    try:
        total_units = int(request.form.get('total_units') or 0)
        base_rent   = float(request.form.get('base_rent') or 0)
    except (ValueError, TypeError):
        total_units, base_rent = 0, 0.0

    if not name or not address:
        flash('Name and address are required.', 'error')
        return redirect(url_for('agent.agent_properties'))

    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        # properties.landlord_id is NOT NULL — agent acts as landlord when self-creating
        cur.execute("""
            INSERT INTO properties
                (landlord_id, agent_id, name, address, city, type, total_units,
                 base_rent, description, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active', NOW())
        """, (agent_id, agent_id, name, address, city, prop_type, total_units, base_rent, description))
        new_id = cur.lastrowid
        conn.commit()

        image_file = request.files.get('image')
        if new_id and image_file and image_file.filename:
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            filename = save_property_image(image_file, new_id, upload_folder)
            if filename:
                cur.execute("UPDATE properties SET image = %s WHERE id = %s", (filename, new_id))
                conn.commit()

        flash(f'"{name}" created successfully!', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Error creating property: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_properties'))


@agent_bp.route('/agent/properties/edit/<int:property_id>', methods=['POST'])
@login_required
@agent_required
def agent_edit_property(property_id):
    agent_id    = session['user_id']
    name        = (request.form.get('name') or '').strip()
    address     = (request.form.get('address') or '').strip()
    city        = (request.form.get('city') or '').strip()
    prop_type   = request.form.get('type', '').strip()
    status      = request.form.get('status', 'Active').strip()
    description = (request.form.get('description') or '').strip()

    try:
        total_units = int(request.form.get('total_units') or 0)
        base_rent   = float(request.form.get('base_rent') or 0)
    except (ValueError, TypeError):
        total_units, base_rent = 0, 0.0

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("SELECT image FROM properties WHERE id = %s AND agent_id = %s", (property_id, agent_id))
        prop = cur.fetchone()
        if not prop:
            flash('Property not found.', 'error')
            return redirect(url_for('agent.agent_properties'))

        upload_folder  = os.path.join(current_app.root_path, 'static', 'uploads')
        image_file     = request.files.get('image')
        new_filename   = None

        if image_file and image_file.filename:
            new_filename = save_property_image(image_file, property_id, upload_folder)
            old_filename = (prop or {}).get('image')
            if new_filename and old_filename:
                old_path = os.path.join(upload_folder, 'properties', old_filename)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass

        if new_filename:
            cur.execute("""
                UPDATE properties
                SET name=%s, address=%s, city=%s, `type`=%s, total_units=%s,
                    base_rent=%s, description=%s, status=%s, image=%s
                WHERE id=%s AND agent_id=%s
            """, (name, address, city, prop_type, total_units, base_rent, description, status, new_filename, property_id, agent_id))
        else:
            cur.execute("""
                UPDATE properties
                SET name=%s, address=%s, city=%s, `type`=%s, total_units=%s,
                    base_rent=%s, description=%s, status=%s
                WHERE id=%s AND agent_id=%s
            """, (name, address, city, prop_type, total_units, base_rent, description, status, property_id, agent_id))

        conn.commit()
        flash('Property updated successfully!', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Error updating property: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_properties'))


@agent_bp.route('/agent/properties/delete/<int:property_id>', methods=['POST'])
@login_required
@agent_required
def agent_delete_property(property_id):
    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("SELECT image FROM properties WHERE id = %s AND agent_id = %s", (property_id, agent_id))
        prop = cur.fetchone()
        if not prop:
            flash('Property not found.', 'error')
            return redirect(url_for('agent.agent_properties'))

        cur.execute("DELETE FROM properties WHERE id = %s AND agent_id = %s", (property_id, agent_id))
        conn.commit()

        if prop and prop.get('image'):
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            image_path = os.path.join(upload_folder, 'properties', prop['image'])
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception:
                    pass
        flash('Property deleted successfully.', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Error deleting property: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_properties'))


# ─────────────────────────────────────────────
# UNITS
# ─────────────────────────────────────────────

@agent_bp.route('/agent/properties/<int:property_id>/units')
@login_required
@agent_required
def agent_get_units(property_id):
    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT id FROM properties WHERE id = %s AND agent_id = %s", (property_id, agent_id))
    if not cur.fetchone():
        cur.close()
        return {'error': 'Not found'}, 404

    cur.execute("""
        SELECT u.id, u.unit_number, u.floor, u.type, u.rent, u.status,
               u.tenant_id,
               t.name  AS tenant_name,
               t.phone AS tenant_phone
        FROM units u
        LEFT JOIN tenants t ON t.id = u.tenant_id
        WHERE u.property_id = %s
        ORDER BY u.unit_number
    """, (property_id,))
    rows = cur.fetchall()
    cur.close()
    return {'units': serialize_units(rows)}


@agent_bp.route('/agent/units')
@login_required
@agent_required
def agent_units():
    agent_id = session['user_id']
    cur = get_cursor()
    try:
        cur.execute("""
            SELECT id, name, address, city, type
            FROM properties WHERE agent_id = %s ORDER BY name
        """, (agent_id,))
        properties = [dict(r) for r in cur.fetchall()]

        # Tenants — name via tenants.name; unit number via join
        cur.execute("""
            SELECT t.id, t.name, u.unit_number AS unit, t.phone
            FROM tenants t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE p.agent_id = %s
            ORDER BY t.name
        """, (agent_id,))
        tenants = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(*) AS total FROM units u
            JOIN properties p ON p.id = u.property_id WHERE p.agent_id = %s
        """, (agent_id,))
        total_units = int((cur.fetchone() or {}).get('total') or 0)

        cur.execute("""
            SELECT COUNT(*) AS total FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE p.agent_id = %s AND u.status = 'Occupied'
        """, (agent_id,))
        occupied = int((cur.fetchone() or {}).get('total') or 0)

        cur.execute("""
            SELECT COUNT(*) AS total FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE p.agent_id = %s AND u.status = 'Vacant'
        """, (agent_id,))
        vacant = int((cur.fetchone() or {}).get('total') or 0)

        stats = {'total_units': total_units, 'occupied': occupied, 'vacant': vacant}
    finally:
        cur.close()
    return render_template('units.html', user=session, properties=properties, tenants=tenants, stats=stats)


@agent_bp.route('/agent/units/add', methods=['POST'])
@login_required
@agent_required
def agent_add_unit():
    agent_id    = session['user_id']
    property_id = (request.form.get('property_id') or '').strip()
    unit_number = (request.form.get('unit_number') or '').strip()
    unit_type   = request.form.get('type', '1 Bedroom')
    status      = (request.form.get('status') or 'Vacant').strip() or 'Vacant'
    tenant_id_raw = (request.form.get('tenant_id') or '').strip()

    try:
        floor = int(request.form.get('floor') or 1)
    except ValueError:
        floor = 1
    try:
        rent = float(request.form.get('rent') or 0)
    except ValueError:
        rent = 0.0
    try:
        tenant_id = int(tenant_id_raw) if tenant_id_raw else None
    except ValueError:
        tenant_id = None

    if not property_id or not unit_number:
        flash('Property and unit number are required.', 'error')
        return redirect(request.referrer or url_for('agent.agent_properties'))
    try:
        property_id_int = int(property_id)
    except ValueError:
        flash('Invalid property.', 'error')
        return redirect(request.referrer or url_for('agent.agent_properties'))

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("SELECT id FROM properties WHERE id = %s AND agent_id = %s", (property_id_int, agent_id))
        if not cur.fetchone():
            flash('Property not found.', 'error')
            return redirect(request.referrer or url_for('agent.agent_properties'))

        cur.execute(
            "SELECT id FROM units WHERE property_id = %s AND unit_number = %s",
            (property_id_int, unit_number)
        )
        if cur.fetchone():
            flash(f'Unit {unit_number} already exists in this property.', 'error')
            return redirect(request.referrer or url_for('agent.agent_properties'))

        if tenant_id:
            cur.execute("""
                SELECT t.id FROM tenants t
                JOIN properties p ON p.id = t.property_id
                WHERE t.id = %s AND p.agent_id = %s
            """, (tenant_id, agent_id))
            if not cur.fetchone():
                flash('Selected tenant not found for your account.', 'error')
                return redirect(request.referrer or url_for('agent.agent_units'))
            if status != 'Maintenance':
                status = 'Occupied'
        else:
            if status == 'Occupied':
                status = 'Vacant'

        cur.execute("""
            INSERT INTO units (property_id, unit_number, floor, type, rent, status, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (property_id_int, unit_number, floor, unit_type, rent, status, tenant_id))
        new_unit_id = cur.lastrowid
        conn.commit()

        # Keep tenants.unit_id in sync
        if tenant_id:
            cur.execute("UPDATE tenants SET unit_id = %s WHERE id = %s", (new_unit_id, tenant_id))
            conn.commit()

        sync_unit_count(property_id_int)
        flash(f'Unit {unit_number} added successfully!', 'success')
        return redirect(request.referrer or url_for('agent.agent_units'))
    except Exception as e:
        conn.rollback()
        flash(f'Error adding unit: {str(e)}', 'error')
        return redirect(request.referrer or url_for('agent.agent_units'))
    finally:
        cur.close()


@agent_bp.route('/agent/units/edit/<int:unit_id>', methods=['POST'])
@login_required
@agent_required
def agent_edit_unit(unit_id):
    agent_id    = session['user_id']
    unit_number = request.form.get('unit_number', '').strip()
    floor       = request.form.get('floor') or None
    unit_type   = request.form.get('type', '')
    status      = request.form.get('status', 'Vacant')
    rent        = request.form.get('rent') or 0
    tenant_id_raw = (request.form.get('tenant_id') or '').strip()

    try:
        floor = int(floor) if floor else None
        rent  = float(rent)
    except (ValueError, TypeError):
        floor, rent = None, 0.0
    try:
        tenant_id = int(tenant_id_raw) if tenant_id_raw else None
    except ValueError:
        tenant_id = None

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT u.id, u.property_id, u.tenant_id
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE u.id = %s AND p.agent_id = %s
        """, (unit_id, agent_id))
        unit_row = cur.fetchone()
        if not unit_row:
            flash('Unit not found.', 'error')
            return redirect(url_for('agent.agent_units'))

        property_id        = unit_row.get('property_id')
        previous_tenant_id = unit_row.get('tenant_id')

        # Clear old tenant's unit_id if changing tenant
        if previous_tenant_id and previous_tenant_id != tenant_id:
            cur.execute(
                "UPDATE tenants SET unit_id = NULL WHERE id = %s AND unit_id = %s",
                (previous_tenant_id, unit_id),
            )

        if tenant_id:
            cur.execute("""
                SELECT t.id FROM tenants t
                JOIN properties p ON p.id = t.property_id
                WHERE t.id = %s AND p.agent_id = %s
            """, (tenant_id, agent_id))
            if not cur.fetchone():
                flash('Selected tenant not found for your account.', 'error')
                return redirect(url_for('agent.agent_units'))

            # Vacate any other unit this tenant was assigned to
            cur.execute("""
                UPDATE units u
                JOIN properties p ON p.id = u.property_id
                SET u.tenant_id = NULL,
                    u.status = CASE WHEN u.status='Occupied' THEN 'Vacant' ELSE u.status END
                WHERE u.tenant_id = %s AND u.id <> %s AND p.agent_id = %s
            """, (tenant_id, unit_id, agent_id))

            # Update tenant record — use unit_id (FK) and amount for rent
            cur.execute("""
                UPDATE tenants
                SET property_id = %s, unit_id = %s, amount = %s
                WHERE id = %s
            """, (property_id, unit_id, rent, tenant_id))

            if status != 'Maintenance':
                status = 'Occupied'
        else:
            if status == 'Occupied':
                status = 'Vacant'

        cur.execute("""
            UPDATE units
            SET unit_number=%s, floor=%s, type=%s, status=%s, rent=%s, tenant_id=%s
            WHERE id=%s
        """, (unit_number, floor, unit_type, status, rent, tenant_id, unit_id))
        conn.commit()
        flash('Unit updated successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating unit: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_units'))


@agent_bp.route('/agent/units/delete/<int:unit_id>', methods=['POST'])
@login_required
@agent_required
def agent_delete_unit(unit_id):
    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT u.id, u.unit_number, u.property_id
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE u.id = %s AND p.agent_id = %s
        """, (unit_id, agent_id))
        unit = cur.fetchone()
        if not unit:
            flash('Unit not found.', 'error')
            return redirect(request.referrer or url_for('agent.agent_units'))

        property_id = unit['property_id']
        # Orphan tenant's unit reference before deleting
        cur.execute("UPDATE tenants SET unit_id = NULL WHERE unit_id = %s", (unit_id,))
        cur.execute("DELETE FROM units WHERE id = %s", (unit_id,))
        conn.commit()
        sync_unit_count(property_id)
        flash(f"Unit {unit['unit_number']} deleted.", 'success')
        return redirect(request.referrer or url_for('agent.agent_units'))
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting unit: {str(e)}', 'error')
        return redirect(request.referrer or url_for('agent.agent_units'))
    finally:
        cur.close()


# ─────────────────────────────────────────────
# TENANTS
# ─────────────────────────────────────────────

@agent_bp.route('/agent/tenants')
@login_required
@agent_required
def agent_tenants():
    agent_id = session['user_id']
    cur = get_cursor()
    cur.execute("""
        SELECT t.id, t.user_id, t.name, t.name, t.email, t.phone,
               t.amount, t.status, t.property_id, t.created_at,
               u.unit_number,
               p.name AS property_name
        FROM   tenants t
        LEFT JOIN properties p ON p.id = t.property_id
        LEFT JOIN units u      ON u.id = t.unit_id
        WHERE  p.agent_id = %s
        ORDER  BY t.created_at DESC
    """, (agent_id,))
    tenant_list = []
    for row in cur.fetchall():
        t = dict(row)
        if not t.get('id'):
            continue
        t['id']           = int(t['id'])
        t['rent']         = float(t.get('amount') or 0)
        t['unit_number']  = t.get('unit_number') or '—'
        t['property_name'] = t.get('property_name') or '—'
        # No lease_start/lease_end in tenants table — omit or show placeholder
        t['lease_start']  = '—'
        t['lease_end']    = '—'
        status = (t.get('status') or 'Active').strip().title()
        t['status']       = status
        t['status_color'] = 'active' if status == 'Active' else 'expiring' if status == 'Expiring' else 'inactive'
        tenant_list.append(t)

    cur.execute("SELECT id, name FROM properties WHERE agent_id = %s ORDER BY name", (agent_id,))
    properties = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT u.id, u.unit_number, p.name AS property_name, u.rent
        FROM units u
        JOIN properties p ON p.id = u.property_id
        WHERE u.status = 'Vacant' AND p.agent_id = %s
        ORDER BY p.name, u.unit_number
        LIMIT 20
    """, (agent_id,))
    vacant_units = [dict(r) for r in cur.fetchall()]

    today       = date.today()
    month_start = today.replace(day=1)

    cur.execute("""
        SELECT COUNT(*) AS cnt FROM tenants t
        JOIN properties p ON p.id = t.property_id
        WHERE p.agent_id = %s AND t.created_at >= %s
    """, (agent_id, month_start))
    new_this_month = (cur.fetchone() or {}).get('cnt', 0)

    # Expiring: use leases table since tenants has no lease_end
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM leases l
        JOIN properties p ON p.id = l.property_id
        WHERE p.agent_id = %s
          AND l.end_date BETWEEN %s AND %s
          AND LOWER(l.status) = 'active'
    """, (agent_id, today, today + timedelta(days=60)))
    expiring = (cur.fetchone() or {}).get('cnt', 0)

    cur.execute("""
        SELECT COUNT(*) AS cnt FROM units u
        JOIN properties p ON u.property_id = p.id
        WHERE p.agent_id = %s AND u.status = 'Vacant'
    """, (agent_id,))
    vacant_count = (cur.fetchone() or {}).get('cnt', 0)

    stats = {'new_this_month': new_this_month, 'expiring_leases': expiring, 'vacant': vacant_count}
    cur.close()
    return render_template('tenant.html',
        user=session, tenant=tenant_list, properties=properties,
        vacant_units=vacant_units, stats=stats,
        pending_overdue=get_overdue_count(agent_id),
    )


@agent_bp.route('/agent/tenants/add', methods=['POST'])
@login_required
@agent_required
def agent_add_tenant():
    name        = request.form.get('name', '').strip()
    phone       = request.form.get('phone', '').strip()
    email       = request.form.get('email', '').strip()
    first_name  = request.form.get('first_name', '').strip()
    last_name   = request.form.get('last_name', '').strip()
    amount      = request.form.get('amount', '0').strip()
    property_id = request.form.get('property_id', '').strip()
    unit_id_raw = request.form.get('unit_id', '').strip()

    # Allow name to be derived from first+last if not supplied separately
    if not name and first_name:
        name = f"{first_name} {last_name}".strip()

    if not name or not phone or not property_id:
        flash('Name, phone, and property are required.', 'error')
        return redirect(url_for('agent.agent_tenants'))

    try:
        property_id_int = int(property_id)
        amount_f        = float(amount)
        unit_id         = int(unit_id_raw) if unit_id_raw else None
    except ValueError:
        flash('Invalid property, unit, or rent amount.', 'error')
        return redirect(url_for('agent.agent_tenants'))

    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("SELECT id FROM properties WHERE id = %s AND agent_id = %s", (property_id_int, agent_id))
        if not cur.fetchone():
            flash('Property not found.', 'error')
            return redirect(url_for('agent.agent_tenants'))

        cur.execute("""
            INSERT INTO tenants
                (name, phone, email, amount, status,
                 property_id, unit_id, created_at)
            VALUES (%s, %s, %s, %s, 'Active', %s, %s, NOW())
        """, (name, phone, email, amount_f, property_id_int, unit_id))
        new_tenant_id = cur.lastrowid

        # Mark unit as occupied
        if unit_id:
            cur.execute(
                "UPDATE units SET status='Occupied', tenant_id=%s WHERE id=%s",
                (new_tenant_id, unit_id)
            )
        conn.commit()
        flash(f'{name} added successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error adding tenant: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_tenants'))


@agent_bp.route('/agent/tenants/edit/<int:tenant_id>', methods=['POST'])
@login_required
@agent_required
def agent_edit_tenant(tenant_id):
    name        = request.form.get('name', '').strip()
    phone       = request.form.get('phone', '').strip()
    email       = request.form.get('email', '').strip()
    first_name  = request.form.get('first_name', '').strip()
    last_name   = request.form.get('last_name', '').strip()
    amount      = request.form.get('amount', '0').strip()
    property_id = request.form.get('property_id', '').strip()
    unit_id_raw = request.form.get('unit_id', '').strip()

    try:
        amount_f    = float(amount) if amount != '' else 0.0
        property_id = int(property_id) if property_id else None
        unit_id     = int(unit_id_raw) if unit_id_raw else None
    except ValueError:
        flash('Invalid values.', 'error')
        return redirect(url_for('agent.agent_tenants'))

    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        if not name and first_name:
            name = f"{first_name} {last_name}".strip()

        cur.execute("""
            SELECT t.id FROM tenants t
            JOIN properties p ON p.id = t.property_id
            WHERE t.id = %s AND p.agent_id = %s
        """, (tenant_id, agent_id))
        if not cur.fetchone():
            flash('Tenant not found.', 'error')
            return redirect(url_for('agent.agent_tenants'))

        if property_id:
            cur.execute("SELECT id FROM properties WHERE id = %s AND agent_id = %s", (property_id, agent_id))
            if not cur.fetchone():
                flash('Property not found.', 'error')
                return redirect(url_for('agent.agent_tenants'))

        cur.execute("""
            UPDATE tenants
            SET name=%s, phone=%s, email=%s,
                amount=%s, property_id=%s, unit_id=%s
            WHERE id=%s
        """, (name, phone, email, amount_f, property_id, unit_id, tenant_id))

        if unit_id:
            cur.execute(
                "UPDATE units SET status='Occupied', tenant_id=%s WHERE id=%s",
                (tenant_id, unit_id)
            )
        conn.commit()
        flash('Tenant updated successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating tenant: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_tenants'))


@agent_bp.route('/agent/tenants/<int:tenant_id>/delete', methods=['POST'])
@login_required
@agent_required
def agent_delete_tenant(tenant_id):
    agent_id = session['user_id']
    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT t.id, t.name, t.unit_id
            FROM tenants t
            JOIN properties p ON p.id = t.property_id
            WHERE t.id = %s AND p.agent_id = %s
        """, (tenant_id, agent_id))
        t = cur.fetchone()
        if not t:
            flash('Tenant not found.', 'error')
            return redirect(url_for('agent.agent_tenants'))

        # Free the unit
        if t.get('unit_id'):
            cur.execute(
                "UPDATE units SET status='Vacant', tenant_id=NULL WHERE id=%s AND tenant_id=%s",
                (t['unit_id'], tenant_id)
            )
        cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        conn.commit()
        flash(f'{t.get("name") or "Tenant"} removed successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error removing tenant: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_tenants'))


# ─────────────────────────────────────────────
# MAINTENANCE
# ─────────────────────────────────────────────

@agent_bp.route('/agent/maintenance')
@login_required
@agent_required
def agent_maintenance():
    agent_id = session['user_id']
    cur = get_cursor()
    # maintenance_requests.property_id exists — use it directly (faster, no unit join needed)
    cur.execute("""
        SELECT m.id, m.title, m.description, m.priority, m.status,
               m.unit_id, 
               p.name AS property_name,
               u.unit_number,
               COALESCE(t.name, '—') AS tenant_name,
               m.created_at, m.updated_at
        FROM maintenance_requests m
        LEFT JOIN properties p ON p.id = m.property_id
        LEFT JOIN units u      ON u.id = m.unit_id
        LEFT JOIN tenants t    ON t.unit_id = m.unit_id
        WHERE p.agent_id = %s
        ORDER BY FIELD(m.priority,'High','Medium','Low'), m.created_at DESC
    """, (agent_id,))
    tickets = [dict(r) for r in cur.fetchall()]

    open_count  = sum(1 for t in tickets if (t.get('status') or '').lower() in {'open', 'pending'})
    in_progress = sum(1 for t in tickets if (t.get('status') or '').lower() in {'in progress', 'in_progress'})
    urgent      = sum(1 for t in tickets if (t.get('priority') or '').lower() in {'high', 'urgent'})

    today = date.today()
    month_start = today.replace(day=1)
    resolved_this_month = sum(
        1 for t in tickets
        if (t.get('status') or '').lower() in {'resolved', 'closed'}
        and t.get('updated_at')
        and t['updated_at'].date() >= month_start
    )
    cur.close()
    return render_template('maintenance.html',
        user=session, tickets=tickets,
        open_count=open_count, urgent_count=urgent,
        in_progress_count=in_progress,
        resolved_this_month=resolved_this_month,
        pending_overdue=get_overdue_count(agent_id),
    )


@agent_bp.route('/agent/maintenance/<int:ticket_id>/update', methods=['POST'])
@login_required
@agent_required
def update_ticket(ticket_id):
    new_status = request.form.get('status', '').strip()
    if new_status not in {'Open', 'In Progress', 'Resolved', 'Closed'}:
        flash('Invalid status.', 'error')
        return redirect(url_for('agent.agent_maintenance'))

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        # Use maintenance_requests.property_id directly
        cur.execute("""
            UPDATE maintenance_requests m
            JOIN properties p ON p.id = m.property_id
            SET m.status = %s, m.updated_at = NOW()
            WHERE m.id = %s AND p.agent_id = %s
        """, (new_status, ticket_id, session['user_id']))
        conn.commit()
        flash('Ticket updated.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_maintenance'))


# ─────────────────────────────────────────────
# NOTICES
# ─────────────────────────────────────────────

@agent_bp.route('/agent/notices')
@login_required
@agent_required
def agent_notices():
    agent_id = session['user_id']
    cur = get_cursor()
    # notices has title + message columns
    cur.execute("""
        SELECT id, title, message, type, created_at AS sent_at
        FROM   notices WHERE sender_id = %s
        ORDER  BY created_at DESC
    """, (agent_id,))
    notices = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT id, name FROM properties WHERE agent_id = %s ORDER BY name", (agent_id,))
    properties = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT t.id, t.name, t.email, t.phone, t.property_id,
               u.unit_number,
               p.name AS property_name
        FROM tenants t
        JOIN properties p ON p.id = t.property_id
        LEFT JOIN units u ON u.id = t.unit_id
        WHERE p.agent_id = %s
        ORDER BY p.name, u.unit_number, t.name
    """, (agent_id,))
    tenants = [dict(r) for r in cur.fetchall()]

    today = date.today()
    month_start = today.replace(day=1)
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM notices
        WHERE sender_id = %s AND created_at >= %s
    """, (agent_id, month_start))
    sent_this_month = int((cur.fetchone() or {}).get('cnt') or 0)
    last_sent = notices[0]['sent_at'] if notices else None
    cur.close()
    return render_template('send_notices.html',
        user=session, notices=notices, properties=properties, tenants=tenants,
        sent_this_month=sent_this_month, recipients_total=len(tenants),
        last_sent=last_sent, pending_overdue=get_overdue_count(agent_id),
    )


@agent_bp.route('/agent/notices/send', methods=['POST'])
@login_required
@agent_required
def notice():
    agent_id    = session['user_id']
    subject     = (request.form.get('subject') or '').strip()
    body        = (request.form.get('message') or '').strip()
    notice_type = (request.form.get('type') or 'normal').strip()
    via         = set(request.form.getlist('via'))

    tenant_ids = [t for t in request.form.getlist('tenant_ids') if str(t).strip()]
    if not tenant_ids:
        flash('Select at least one recipient.', 'error')
        return redirect(url_for('agent.agent_notices'))
    if not body and not subject:
        flash('Message cannot be empty.', 'error')
        return redirect(url_for('agent.agent_notices'))

    message = f"{subject}\n\n{body}".strip() if subject else body
    title   = subject or 'Notice'

    conn = get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        placeholders = ",".join(["%s"] * len(tenant_ids))
        cur.execute(f"""
            SELECT DISTINCT t.property_id, p.landlord_id
            FROM tenants t
            JOIN properties p ON p.id = t.property_id
            WHERE t.id IN ({placeholders}) AND p.agent_id = %s
        """, (*tenant_ids, agent_id))
        property_rows = [dict(r) for r in (cur.fetchall() or []) if r.get('property_id')]

        if not property_rows:
            flash('Selected recipients are not valid for your account.', 'error')
            return redirect(url_for('agent.agent_notices'))

        # notices: landlord_id, property_id, title, message, type, sender_id
        for row in property_rows:
            cur.execute("""
                INSERT INTO notices (landlord_id, sender_id, property_id, title, message, type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (row.get('landlord_id'), agent_id, row.get('property_id'), title, message, notice_type))

        conn.commit()
        via_label = ", ".join(sorted(via)) if via else "in_app"
        flash(f'Notice sent ({via_label}) for {len(tenant_ids)} recipient(s).', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(url_for('agent.agent_notices'))


# ─────────────────────────────────────────────
# PAYMENTS
# ─────────────────────────────────────────────

@agent_bp.route('/agent/payments')
@login_required
@agent_required
def agent_payments():
    agent_id       = session['user_id']
    selected_month = (request.args.get('month') or '').strip() or date.today().strftime("%B %Y")
    property_id    = request.args.get('property_id', '').strip()

    try:
        property_id_int = int(property_id) if property_id else None
    except ValueError:
        property_id_int = None

    cur = get_cursor()
    cur.execute("SELECT id, name FROM properties WHERE agent_id = %s ORDER BY name", (agent_id,))
    properties  = [dict(r) for r in cur.fetchall()]
    prop_ids    = {p['id'] for p in properties}
    if property_id_int not in prop_ids:
        property_id_int = None

    cur.execute("""
        SELECT DISTINCT pay.month AS month
        FROM payments pay
        JOIN properties p ON p.id = pay.property_id
        WHERE p.agent_id = %s AND pay.month IS NOT NULL AND pay.month != ''
        ORDER BY pay.paid_on DESC LIMIT 24
    """, (agent_id,))
    available_months = [r.get('month') for r in cur.fetchall() if (r.get('month') or '').strip()]
    if selected_month not in available_months:
        available_months = [selected_month] + available_months
    seen = set()
    available_months = [m for m in available_months if not (m in seen or seen.add(m))]

    sql = """
        SELECT t.id, t.name, t.phone, t.email, t.amount,
               u.unit_number,
               p.id AS property_id, p.name AS property_name
        FROM tenants t
        JOIN properties p ON p.id = t.property_id
        LEFT JOIN units u ON u.id = t.unit_id
        WHERE p.agent_id = %s
    """
    params = [agent_id]
    if property_id_int:
        sql += " AND p.id = %s"
        params.append(property_id_int)
    sql += " ORDER BY p.name, t.name"

    cur.execute(sql, tuple(params))
    tenants = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT pay.tenant_id,
               pay.Amount AS amount,
               pay.paid_on, pay.status, pay.method, pay.reference
        FROM payments pay
        JOIN properties p ON p.id = pay.property_id
        WHERE p.agent_id = %s AND pay.month = %s
    """, (agent_id, selected_month))
    payment_by_tenant = {r['tenant_id']: dict(r) for r in cur.fetchall() if r.get('tenant_id')}

    payments = []
    for t in tenants:
        tid = t.get('id')
        pay = payment_by_tenant.get(tid) or {}
        is_paid = (pay.get('status') or '').strip().lower() == 'paid'
        payments.append({
            'tenant_id':    tid,
            'full_name':    t.get('name'),
            'unit':         t.get('unit_number') or '—',
            'property_name': t.get('property_name') or '—',
            'amount_due':   float(pay.get('amount') or t.get('amount') or 0),
            'paid_on':      str(pay.get('paid_on'))[:10] if pay.get('paid_on') else '—',
            'method':       pay.get('method') or '—',
            'status':       'Paid' if is_paid else 'Unpaid',
            'reference':    pay.get('reference') or '—',
        })

    collected       = sum(p['amount_due'] for p in payments if p['status'] == 'Paid')
    outstanding     = sum(p['amount_due'] for p in payments if p['status'] != 'Paid')
    units_paid      = sum(1 for p in payments if p['status'] == 'Paid')
    total_units_cnt = len(payments)
    collection_rate = int((collected / (collected + outstanding) * 100) if (collected + outstanding) else 0)

    stats = {
        'month': selected_month, 'collected': collected, 'outstanding': outstanding,
        'units_paid': units_paid, 'total_units': total_units_cnt, 'collection_rate': collection_rate,
    }
    cur.close()
    return render_template('agent_payments.html',
        user=session, properties=properties,
        selected_property_id=property_id_int, tenants=tenants,
        payments=payments, stats=stats,
        available_months=available_months, selected_month=selected_month,
        paid_count=units_paid, unpaid_count=total_units_cnt - units_paid,
        pending_overdue=get_overdue_count(agent_id),
    )


# ─────────────────────────────────────────────
# PENALTIES
# ─────────────────────────────────────────────

@agent_bp.route('/agent/penalties')
@login_required
@agent_required
def agent_penalties():
    agent_id = session['user_id']
    cur = get_cursor()
    cur.execute("""
        SELECT t.name AS tenant_name,
               pay.Amount AS amount, pay.paid_on AS date,
               pay.status, u.unit_number,
               p.name AS property_name, pay.month
        FROM   payments pay
        JOIN   tenants t    ON pay.tenant_id    = t.id
        JOIN   properties p ON pay.property_id  = p.id
        LEFT JOIN units u   ON pay.unit_id      = u.id
        WHERE  p.agent_id = %s AND LOWER(pay.status) = 'overdue'
        ORDER  BY pay.paid_on DESC
    """, (agent_id,))
    penalties = []
    for row in cur.fetchall():
        r = dict(row)
        amt = float(r.get('amount') or 0)
        r['amount']          = amt
        r['agent_commission'] = round(amt * COMMISSION_RATE, 2)
        r['date']            = str(r.get('date'))[:10] if r.get('date') else '—'
        penalties.append(r)

    total_overdue_amount = round(sum(p['amount'] for p in penalties), 2)
    total_agent_owed     = round(sum(p['agent_commission'] for p in penalties), 2)
    cur.close()
    return render_template('penalties.html',
        user=session, penalties=penalties,
        total_overdue_amount=total_overdue_amount,
        total_agent_owed=total_agent_owed,
        commission_rate_pct=int(COMMISSION_RATE * 100),
        pending_overdue=len(penalties),
    )


# ─────────────────────────────────────────────
# WALLET
# ─────────────────────────────────────────────

@agent_bp.route('/agent/wallet')
@login_required
@agent_required
def agent_wallet():
    agent_id = session['user_id']
    cur = get_cursor()

    cur.execute("""
        SELECT SUM(pay.Amount)       AS total_collected,
               SUM(pay.Amount * %s)  AS total_commission,
               COUNT(*)              AS total_transactions
        FROM   payments pay
        JOIN   properties p ON pay.property_id = p.id
        WHERE  p.agent_id = %s AND LOWER(pay.status) = 'paid'
    """, (COMMISSION_RATE, agent_id))
    wallet = dict(cur.fetchone() or {})
    wallet['total_collected']    = float(wallet.get('total_collected') or 0)
    wallet['total_commission']   = float(wallet.get('total_commission') or 0)
    wallet['total_transactions'] = int(wallet.get('total_transactions') or 0)

    cur.execute("""
        SELECT SUM(pay.Amount)       AS overdue_total,
               SUM(pay.Amount * %s)  AS agent_penalty_owed,
               COUNT(*)              AS overdue_count
        FROM payments pay
        JOIN properties p ON pay.property_id = p.id
        WHERE p.agent_id = %s AND LOWER(pay.status) = 'overdue'
    """, (COMMISSION_RATE, agent_id))
    penalty_summary = dict(cur.fetchone() or {})
    penalty_summary['overdue_total']       = float(penalty_summary.get('overdue_total') or 0)
    penalty_summary['agent_penalty_owed']  = float(penalty_summary.get('agent_penalty_owed') or 0)
    penalty_summary['overdue_count']       = int(penalty_summary.get('overdue_count') or 0)

    cur.execute("""
        SELECT p.id AS property_id, p.name AS property_name,
               SUM(pay.Amount)       AS collected,
               SUM(pay.Amount * %s)  AS commission,
               COUNT(*)              AS tx_count
        FROM payments pay
        JOIN properties p ON pay.property_id = p.id
        WHERE p.agent_id = %s AND LOWER(pay.status) = 'paid'
        GROUP BY p.id, p.name
        ORDER BY commission DESC
    """, (COMMISSION_RATE, agent_id))
    property_breakdown = []
    for row in cur.fetchall():
        r = dict(row)
        r['collected']  = float(r.get('collected') or 0)
        r['commission'] = float(r.get('commission') or 0)
        r['tx_count']   = int(r.get('tx_count') or 0)
        property_breakdown.append(r)

    cur.execute("""
        SELECT t.name AS tenant_name,
               pay.Amount      AS rent_amount,
               pay.Amount * %s AS commission,
               pay.paid_on     AS date,
               p.name          AS property_name
        FROM   payments pay
        JOIN   tenants t    ON pay.tenant_id    = t.id
        JOIN   properties p ON pay.property_id  = p.id
        WHERE  p.agent_id = %s AND LOWER(pay.status) = 'paid'
        ORDER  BY pay.paid_on DESC
        LIMIT  20
    """, (COMMISSION_RATE, agent_id))
    transactions = []
    for row in cur.fetchall():
        r = dict(row)
        r['rent_amount'] = float(r.get('rent_amount') or 0)
        r['commission']  = float(r.get('commission') or 0)
        r['date']        = str(r.get('date'))[:10] if r.get('date') else '—'
        transactions.append(r)
    cur.close()

    return render_template('agent_wallet.html',
        user=session, wallet=wallet, penalty_summary=penalty_summary,
        property_breakdown=property_breakdown,
        commission_rate_pct=int(COMMISSION_RATE * 100),
        transactions=transactions,
        pending_overdue=get_overdue_count(agent_id),
    )


# ─────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────

@agent_bp.route('/agent/reports')
@login_required
@agent_required
def agent_reports():
    agent_id = session['user_id']
    cur = get_cursor()
    cur.execute("""
        SELECT p.name,
               COUNT(u.id)                                         AS total_units,
               SUM(u.status = 'Occupied')                          AS occupied,
               ROUND(SUM(u.status='Occupied') / COUNT(u.id) * 100) AS occupancy_pct
        FROM   properties p
        JOIN   units u ON u.property_id = p.id
        WHERE  p.agent_id = %s
        GROUP  BY p.id, p.name
    """, (agent_id,))
    occupancy_report = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT
            SUM(CASE WHEN LOWER(pay.status)='paid'  THEN pay.Amount ELSE 0 END) AS collected,
            SUM(CASE WHEN LOWER(pay.status)!='paid' THEN pay.Amount ELSE 0 END) AS outstanding
        FROM   payments pay
        JOIN   properties p ON pay.property_id = p.id
        WHERE  p.agent_id = %s
          AND  MONTH(pay.paid_on) = MONTH(NOW())
          AND  YEAR(pay.paid_on)  = YEAR(NOW())
    """, (agent_id,))
    monthly = dict(cur.fetchone() or {})
    cur.close()
    return render_template('reports.html',
        user=session, occupancy_report=occupancy_report, monthly=monthly,
        pending_overdue=get_overdue_count(agent_id),
    )
