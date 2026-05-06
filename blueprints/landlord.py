import os
from datetime import date, timedelta, datetime
from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify, current_app, make_response
from extensions import mysql, get_conn_and_cursor, record_transaction
from helpers import login_required, save_property_image, serialize_units, sync_unit_count, get_landlord_stats
import MySQLdb
import secrets
from werkzeug.security import generate_password_hash

landlord_bp = Blueprint('landlord', __name__)


def _get_conn_cur():
    return get_conn_and_cursor()


# ----------------------
# LANDLORD DASHBOARD
# ----------------------

@landlord_bp.route('/landlord_dashboard')
@login_required
def landlord_dashboard():
    if (session.get('role') or '').lower() != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()

    try:
        cur.execute("SELECT COUNT(*) AS total FROM properties WHERE landlord_id = %s", (landlord_id,))
        total_properties = int((cur.fetchone() or {}).get('total') or 0)

        cur.execute("""
            SELECT COUNT(*) AS total FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE p.landlord_id = %s
        """, (landlord_id,))
        total_units = int((cur.fetchone() or {}).get('total') or 0)

        cur.execute("""
            SELECT COUNT(*) AS total FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE p.landlord_id = %s AND LOWER(u.status) = 'occupied'
        """, (landlord_id,))
        occupied = int((cur.fetchone() or {}).get('total') or 0)
        occupancy_rate = int((occupied / total_units) * 100) if total_units > 0 else 0

        cur.execute("""
            SELECT COALESCE(SUM(pay.Amount), 0) AS total
            FROM payments pay
            JOIN properties p ON p.id = pay.property_id
            WHERE p.landlord_id = %s AND LOWER(pay.status) = 'paid'
        """, (landlord_id,))
        rent_collected = float((cur.fetchone() or {}).get('total') or 0)

        cur.execute("""
            SELECT COALESCE(SUM(pay.Amount), 0) AS total
            FROM payments pay
            JOIN properties p ON p.id = pay.property_id
            WHERE p.landlord_id = %s AND LOWER(pay.status) != 'paid'
        """, (landlord_id,))
        rent_outstanding = float((cur.fetchone() or {}).get('total') or 0)

        # tenant has no `unit` text col - join units for unit_number
        cur.execute("""
            SELECT t.name, u.unit_number, t.amount, t.status, p.name AS property_name
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE p.landlord_id = %s
            ORDER BY t.created_at DESC
            LIMIT 8
        """, (landlord_id,))
        tenant = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT u.id, u.unit_number, u.rent AS rent_amount, u.status, u.property_id,
                   p.name AS property_name
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE p.landlord_id = %s
            ORDER BY u.id DESC LIMIT 5
        """, (landlord_id,))
        properties = [dict(r) for r in cur.fetchall()]

        # payments - use tenant_id FK (not userid alias), Amount (capital A)
        cur.execute("""
            SELECT pay.tenant_id, pay.Amount, pay.status,
                   pay.`phone no` AS phone,
                   p.name AS property_name,
                   pay.paid_on
            FROM payments pay
            LEFT JOIN properties p ON p.id = pay.property_id
            WHERE p.landlord_id = %s
            ORDER BY pay.paid_on DESC LIMIT 5
        """, (landlord_id,))
        recent_payments = []
        for row in cur.fetchall():
            p = dict(row)
            p['amount']  = float(p.get('Amount') or 0)
            p['paid_on'] = str(p.get('paid_on'))[:10] if p.get('paid_on') else '-'
            recent_payments.append(p)

        # notices has title + message columns
        cur.execute("""
            SELECT id, title, message, type, created_at AS sent_at
            FROM notices WHERE sender_id = %s
            ORDER BY created_at DESC LIMIT 5
        """, (landlord_id,))
        notices = [dict(r) for r in cur.fetchall()]

        # maintenance_requests has property_id directly
        cur.execute("""
            SELECT m.id, m.title, m.priority, m.status, m.created_at,
                   u.unit_number,
                   p.name AS property_name
            FROM maintenance_requests m
            LEFT JOIN units u      ON u.id = m.unit_id
            LEFT JOIN properties p ON p.id = m.property_id
            WHERE p.landlord_id = %s
            ORDER BY m.created_at DESC LIMIT 5
        """, (landlord_id,))
        tickets = [dict(r) for r in cur.fetchall()]

    finally:
        try:
            cur.close()
        finally:
            if should_close:
                conn.close()

    return render_template('landlord_dashboard.html',
        user=session,
        total_properties=total_properties,
        total_units=total_units,
        occupancy_rate=occupancy_rate,
        rent_collected=rent_collected,
        rent_outstanding=rent_outstanding,
        tenant=tenant,
        properties=properties,
        recent_payments=recent_payments,
        notices=notices,
        tickets=tickets,
    )


# ----------------------
# PROFILE
# ----------------------

@landlord_bp.route('/profile')
@login_required
def profile():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))
    return render_template('profile.html', user=session)


# ----------------------
# RENT COLLECTION
# ----------------------

@landlord_bp.route('/rent-collection')
@login_required
def rent_collection():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id    = session['user_id']
    selected_month = (request.args.get('month') or '').strip() or date.today().strftime("%B %Y")
    conn, cur, should_close = _get_conn_cur()

    try:
        cur.execute("""
            SELECT DISTINCT pay.month AS month
            FROM payments pay
            JOIN properties p ON p.id = pay.property_id
            WHERE p.landlord_id = %s AND pay.month IS NOT NULL AND pay.month != ''
            ORDER BY pay.paid_on DESC LIMIT 24
        """, (landlord_id,))
        available_months = [r.get('month') for r in cur.fetchall() if (r.get('month') or '').strip()]
        if selected_month not in available_months:
            available_months = [selected_month] + available_months
        seen = set()
        available_months = [m for m in available_months if not (m in seen or seen.add(m))]

        cur.execute("SELECT id, name FROM properties WHERE landlord_id = %s ORDER BY name", (landlord_id,))
        properties = [dict(r) for r in cur.fetchall()]

        # tenant has no `unit` text col - join for unit_number
        cur.execute("""
            SELECT t.id, t.name, t.phone, t.email, t.amount,
                   t.property_id, p.name AS property_name,
                   u.unit_number
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE p.landlord_id = %s
            ORDER BY t.name
        """, (landlord_id,))
        tenant = [dict(r) for r in cur.fetchall()]

        # payments - use tenant_id FK
        cur.execute("""
            SELECT pay.tenant_id,
                   pay.Amount AS amount, pay.status,
                   pay.paid_on, pay.method, pay.reference
            FROM payments pay
            JOIN properties p ON p.id = pay.property_id
            WHERE p.landlord_id = %s AND pay.month = %s
            ORDER BY pay.paid_on DESC
        """, (landlord_id, selected_month))
        pay_map = {}
        for r in cur.fetchall():
            tid = r.get('tenant_id')
            if tid is not None and tid not in pay_map:
                pay_map[tid] = dict(r)

        payments = []
        for t in tenant:
            pr   = pay_map.get(t.get('id')) or {}
            paid = (pr.get('status') or '').strip().lower() == 'paid'
            payments.append({
                'tenant_id':    t.get('id'),
                'full_name':    t.get('name'),
                'phone':        t.get('phone'),
                'unit':         t.get('unit_number') or '-',
                'property_id':  t.get('property_id'),
                'property_name': t.get('property_name') or '-',
                'amount_due':   float(t.get('amount') or 0),
                'amount_paid':  float(pr.get('amount') or 0) if pr else 0,
                'status':       'Paid' if paid else 'Unpaid',
                'paid_on':      str(pr.get('paid_on'))[:10] if pr.get('paid_on') else None,
                'method':       pr.get('method') or '-',
                'reference':    pr.get('reference') or '-',
            })

        paid_rows    = [p for p in payments if p['status'] == 'Paid']
        unpaid_rows  = [p for p in payments if p['status'] != 'Paid']
        total_collected  = sum(p['amount_paid'] for p in paid_rows)
        total_outstanding = sum(p['amount_due'] for p in unpaid_rows)
        total_units      = len(payments)
        units_paid       = len(paid_rows)
        collection_rate  = int((units_paid / total_units) * 100) if total_units > 0 else 0

        stats = {
            'collected': total_collected, 'outstanding': total_outstanding,
            'units_paid': units_paid, 'total_units': total_units,
            'collection_rate': collection_rate, 'overdue_count': 0,
            'month': selected_month,
        }
    finally:
        cur.close()
        if should_close:
            conn.close()

    return render_template('rent_collection.html',
        user=session, payments=payments, tenant=tenant,
        properties=properties, stats=stats,
        available_months=available_months, selected_month=selected_month,
    )


@landlord_bp.route('/rent-collection/record', methods=['POST'])
@login_required
def record_payment():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    tenant_id   = (request.form.get('tenant_id') or '').strip()
    month       = (request.form.get('month') or '').strip() or date.today().strftime("%B %Y")
    amount_raw  = (request.form.get('amount') or '0').strip()
    method      = (request.form.get('method') or 'Cash').strip()
    reference   = (request.form.get('reference') or '').strip()

    try:
        tenant_id_int = int(tenant_id)
        amount = float(amount_raw)
    except ValueError:
        flash('Invalid tenant or amount.', 'error')
        return redirect(url_for('landlord.rent_collection', month=month))

    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT t.id, t.name, t.phone, t.unit_id, t.property_id,
                   u.unit_number
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE t.id = %s AND p.landlord_id = %s
            LIMIT 1
        """, (tenant_id_int, landlord_id))
        t = cur.fetchone()
        if not t:
            flash('Tenant not found for your account.', 'error')
            return redirect(url_for('landlord.rent_collection', month=month))

        # Insert using correct column names from schema
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
            landlord_id,
        ))
        payment_id = cur.lastrowid
        record_transaction(payment_id, t['id'], t.get('property_id'), amount,
                           'Paid', method, reference, None, date.today(), 0)
        conn.commit()
        flash(f"Payment of KES {amount:,.0f} recorded for {t.get('name')}!", 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error recording payment: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.rent_collection', month=month))


# Receipt helpers

def _landlord_tenant_for_doc(landlord_id: int, tenant_id: int):
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT t.id, t.name, t.email, t.phone, t.amount,
                   u.unit_number,
                   p.name AS property_name, p.id AS property_id
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE t.id = %s AND p.landlord_id = %s
            LIMIT 1
        """, (tenant_id, landlord_id))
        return cur.fetchone()
    finally:
        cur.close()
        if should_close:
            conn.close()


@landlord_bp.route('/landlord/tenant/<int:tenant_id>/receipt')
@login_required
def landlord_tenant_receipt(tenant_id):
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    month  = (request.args.get('month') or '').strip() or date.today().strftime("%B %Y")
    tenant = _landlord_tenant_for_doc(landlord_id, tenant_id)
    if not tenant:
        flash('Tenant not found.', 'error')
        return redirect(url_for('landlord.rent_collection', month=month))

    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT Amount AS amount, status, paid_on, method, reference
            FROM payments
            WHERE tenant_id = %s AND property_id = %s AND month = %s
            ORDER BY paid_on DESC LIMIT 1
        """, (tenant_id, tenant.get('property_id'), month))
        pay = cur.fetchone() or {}
    finally:
        cur.close()
        if should_close:
            conn.close()

    html = render_template('payment_doc.html',
        doc_type='Receipt', month=month, tenant=tenant,
        amount=pay.get('amount') if pay.get('amount') is not None else (tenant.get('amount') or 0),
        status=pay.get('status') or 'Unpaid',
        paid_on=pay.get('paid_on'), method=pay.get('method'),
        reference=pay.get('reference'), issued_at=datetime.now(),
    )
    resp = make_response(html)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename="Receipt-{tenant_id}-{month.replace(" ","-")}.html"'
    return resp


@landlord_bp.route('/landlord/bills/create', methods=['POST'])
@login_required
def landlord_create_bill():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    tenant_id   = (request.form.get('tenant_id') or '').strip()
    bill_type   = (request.form.get('bill_type') or 'Other').strip()
    amount_raw  = (request.form.get('amount') or '0').strip()
    due_date    = (request.form.get('due_date') or '').strip()
    month       = (request.form.get('month') or '').strip() or date.today().strftime("%B %Y")

    try:
        tenant_id_int = int(tenant_id)
        amount = float(amount_raw)
    except ValueError:
        flash('Invalid bill data.', 'error')
        return redirect(url_for('landlord.rent_collection', month=month))

    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT t.id, t.unit_id FROM tenant t
            JOIN properties p ON p.id = t.property_id
            WHERE t.id = %s AND p.landlord_id = %s LIMIT 1
        """, (tenant_id_int, landlord_id))
        t = cur.fetchone()
        if not t:
            flash('Tenant not found for your account.', 'error')
            return redirect(url_for('landlord.rent_collection', month=month))

        # bills schema: tenant_id, property_id, unit_id (varchar!), bill_type, amount, due_date, status, month, amount_due
        cur.execute("""
            INSERT INTO bills
                (tenant_id, bill_type, amount, amount_due, due_date, status, month, created_at)
            VALUES (%s, %s, %s, %s, %s, 'Pending', %s, NOW())
        """, (tenant_id_int, bill_type, amount, amount, due_date or None, month))
        conn.commit()
        flash('Bill created.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error creating bill: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.rent_collection', month=month))


@landlord_bp.route('/rent-collection/update-status/<int:payment_id>', methods=['POST'])
@login_required
def update_payment_status(payment_id):
    status = request.form.get('status', 'Paid')
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            UPDATE payments SET status=%s, paid_on=CURDATE()
            WHERE id=%s
        """, (status, payment_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        if should_close:
            conn.close()


# ----------------------
# UNITS
# ----------------------

@landlord_bp.route('/units')
@login_required
def units():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT p.id, p.name, p.address, p.city, p.type,
                   COUNT(u.id) AS total_units,
                   SUM(CASE WHEN u.status='Occupied' THEN 1 ELSE 0 END) AS occupied_count,
                   SUM(CASE WHEN u.status='Vacant'   THEN 1 ELSE 0 END) AS vacant_count
            FROM properties p
            LEFT JOIN units u ON u.property_id = p.id
            WHERE p.landlord_id = %s
            GROUP BY p.id ORDER BY p.name
        """, (landlord_id,))
        properties_data = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT t.id, t.name, u.unit_number AS unit, t.phone, t.property_id
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE p.landlord_id = %s ORDER BY t.name
        """, (landlord_id,))
        tenant = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT id, name FROM properties WHERE landlord_id = %s ORDER BY name
        """, (landlord_id,))
        properties = [dict(r) for r in cur.fetchall()]

        total_units    = sum(p.get('total_units', 0) or 0 for p in properties_data)
        occupied_units = sum(p.get('occupied_count', 0) or 0 for p in properties_data)
        vacant_units   = sum(p.get('vacant_count', 0) or 0 for p in properties_data)
        stats = {'total_units': total_units, 'occupied': occupied_units, 'vacant': vacant_units}
    finally:
        cur.close()
        if should_close:
            conn.close()

    return render_template('units.html',
        user=session, properties_data=properties_data,
        properties=properties, tenant=tenant, stats=stats,
    )


@landlord_bp.route('/properties/<int:property_id>/units')
@login_required
def get_units(property_id):
    if session.get('role') != 'landlord':
        return jsonify({'error': 'Unauthorized'}), 403

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()

    cur.execute(
        "SELECT id FROM properties WHERE id = %s AND landlord_id = %s",
        (property_id, landlord_id)
    )
    if not cur.fetchone():
        cur.close()
        if should_close:
            conn.close()
        return jsonify({'error': 'Not found'}), 404

    cur.execute("""
        SELECT u.id, u.unit_number, u.floor, u.type,
               u.rent, u.status, u.tenant_id,
               t.name  AS tenant_name,
               t.phone AS tenant_phone
        FROM units u
        LEFT JOIN tenant t ON t.id = u.tenant_id
        WHERE u.property_id = %s
        ORDER BY u.unit_number
    """, (property_id,))
    rows = cur.fetchall()
    cur.close()
    if should_close:
        conn.close()
    return jsonify({'units': serialize_units(rows)})


@landlord_bp.route('/units/add', methods=['POST'])
@login_required
def add_unit():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landlord.units'))

    landlord_id   = session['user_id']
    property_id   = request.form.get('property_id', '').strip()
    unit_number   = request.form.get('unit_number', '').strip()
    unit_type     = request.form.get('type', '1 Bedroom')
    tenant_id_raw = request.form.get('tenant_id', '').strip()

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
        return redirect(url_for('landlord.units'))

    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("SELECT id FROM properties WHERE id=%s AND landlord_id=%s", (property_id, landlord_id))
        if not cur.fetchone():
            flash('Property not found.', 'error')
            return redirect(url_for('landlord.units'))

        cur.execute("SELECT id FROM units WHERE property_id=%s AND unit_number=%s", (property_id, unit_number))
        if cur.fetchone():
            flash(f'Unit {unit_number} already exists in this property.', 'error')
            return redirect(url_for('landlord.units'))

        status = 'Vacant'
        if tenant_id:
            # Tenant must exist and belong to the selected property
            cur.execute("SELECT id FROM tenant WHERE id=%s AND property_id=%s", (tenant_id, property_id))
            if not cur.fetchone():
                flash('Selected tenant not found for this property.', 'error')
                return redirect(url_for('landlord.units'))
            status = 'Occupied'

        cur.execute("""
            INSERT INTO units (property_id, unit_number, floor, type, rent, status, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (property_id, unit_number, floor, unit_type, rent, status, tenant_id))
        new_unit_id = cur.lastrowid

        if tenant_id:
            cur.execute("UPDATE tenant SET unit_id=%s WHERE id=%s", (new_unit_id, tenant_id))

        conn.commit()
        sync_unit_count(property_id)
        flash(f'Unit {unit_number} added successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error adding unit: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.units'))


@landlord_bp.route('/units/edit/<int:unit_id>', methods=['POST'])
@login_required
def edit_unit(unit_id):
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landlord.units'))

    landlord_id = session['user_id']

    unit_number   = (request.form.get('unit_number') or '').strip()
    floor_raw     = (request.form.get('floor') or '').strip()
    unit_type     = request.form.get('type', '') or ''
    status        = request.form.get('status', 'Vacant') or 'Vacant'
    rent_raw      = (request.form.get('rent') or '').strip()
    tenant_id_raw = (request.form.get('tenant_id') or '').strip()

    try:
        floor = int(floor_raw) if floor_raw else None
    except ValueError:
        floor = None
    try:
        rent = float(rent_raw) if rent_raw else 0.0
    except ValueError:
        rent = 0.0
    try:
        tenant_id = int(tenant_id_raw) if tenant_id_raw else None
    except ValueError:
        tenant_id = None

    if not unit_number:
        flash('Unit number is required.', 'error')
        return redirect(url_for('landlord.units'))

    conn, cur, should_close = _get_conn_cur()
    try:
        # Verify unit belongs to this landlord and capture current tenant/property
        cur.execute("""
            SELECT u.id, u.property_id, u.tenant_id
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE u.id = %s AND p.landlord_id = %s
        """, (unit_id, landlord_id))
        unit_row = cur.fetchone()
        if not unit_row:
            flash('Unit not found.', 'error')
            return redirect(url_for('landlord.units'))

        property_id = unit_row.get('property_id')
        previous_tenant_id = unit_row.get('tenant_id')

        # Unlink previous tenant if changed
        if previous_tenant_id and previous_tenant_id != tenant_id:
            cur.execute(
                "UPDATE tenant SET unit_id = NULL WHERE id = %s AND unit_id = %s",
                (previous_tenant_id, unit_id),
            )

        if tenant_id:
            # Tenant must belong to the same property and to this landlord
            cur.execute("""
                SELECT t.id
                FROM tenant t
                JOIN properties p ON p.id = t.property_id
                WHERE t.id = %s AND t.property_id = %s AND p.landlord_id = %s
            """, (tenant_id, property_id, landlord_id))
            if not cur.fetchone():
                flash('Selected tenant not found for this property.', 'error')
                return redirect(url_for('landlord.units'))

            # If tenant is already linked to another unit, vacate that unit first
            cur.execute("""
                UPDATE units
                SET tenant_id = NULL,
                    status = CASE WHEN status = 'Occupied' THEN 'Vacant' ELSE status END
                WHERE tenant_id = %s AND id <> %s
            """, (tenant_id, unit_id))

            # Keep tenant record aligned with this unit
            cur.execute("""
                UPDATE tenant
                SET unit_id = %s
                WHERE id = %s
            """, (unit_id, tenant_id))

            # Avoid inconsistent "Vacant" while tenant is assigned
            if status != 'Maintenance':
                status = 'Occupied'
        else:
            # Avoid "Occupied" without a tenant
            if status == 'Occupied':
                status = 'Vacant'

        cur.execute("""
            UPDATE units
            SET unit_number = %s,
                floor = %s,
                type = %s,
                status = %s,
                rent = %s,
                tenant_id = %s
            WHERE id = %s
        """, (unit_number, floor, unit_type, status, rent, tenant_id, unit_id))
        conn.commit()
        flash('Unit updated successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating unit: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.units'))


@landlord_bp.route('/units/delete/<int:unit_id>', methods=['POST'])
@login_required
def delete_unit(unit_id):
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landlord.units'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT u.id, u.unit_number, u.property_id
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE u.id = %s AND p.landlord_id = %s
        """, (unit_id, landlord_id))
        unit = cur.fetchone()
        if not unit:
            flash('Unit not found.', 'error')
            return redirect(url_for('landlord.units'))

        property_id = unit['property_id']
        cur.execute("UPDATE tenant SET unit_id=NULL WHERE unit_id=%s", (unit_id,))
        cur.execute("DELETE FROM units WHERE id=%s", (unit_id,))
        conn.commit()
        sync_unit_count(property_id)
        flash(f'Unit {unit["unit_number"]} deleted.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting unit: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.units'))


# ----------------------
# TENANTS
# ----------------------

@landlord_bp.route('/tenant')
@login_required
def tenant():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()

    try:
        # Tenant list
        cur.execute("""
            SELECT t.id, t.name,
                   t.email, t.phone, t.amount, t.status,
                   t.property_id, t.unit_id, t.created_at,
                   u.unit_number,
                   p.name AS property_name
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE p.landlord_id = %s
            ORDER BY t.created_at DESC
        """, (landlord_id,))
        tenant_list = []
        for row in cur.fetchall():
            t = dict(row)
            if not t.get('id'):
                continue
            t['id']           = int(t['id'])
            t['rent']         = float(t.get('amount') or 0)
            t['unit_number']  = t.get('unit_number') or '-'
            t['property_name'] = t.get('property_name') or '-'
            t['unit_id']      = int(t.get('unit_id') or 0) if t.get('unit_id') else None
            t['property_id']  = int(t.get('property_id') or 0) if t.get('property_id') else None
            t['status']       = t.get('status') or 'Active'
            t['status_color'] = ('active' if t['status'] == 'Active' else
                                 'expiring' if t['status'] == 'Expiring' else 'inactive')
            tenant_list.append(t)

        cur.execute("SELECT id, name FROM properties WHERE landlord_id=%s ORDER BY name", (landlord_id,))
        properties = [dict(r) for r in cur.fetchall()]

        today       = date.today()
        month_start = today.replace(day=1)

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM tenant t
            JOIN properties p ON p.id = t.property_id
            WHERE p.landlord_id=%s AND t.created_at >= %s
        """, (landlord_id, month_start))
        new_this_month = (cur.fetchone() or {}).get('cnt', 0)
        expiring = 0

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM units u
            JOIN properties p ON u.property_id = p.id
            WHERE p.landlord_id=%s AND u.status='Vacant'
        """, (landlord_id,))
        vacant_count = (cur.fetchone() or {}).get('cnt', 0)

    finally:
        cur.close()
        if should_close:
            conn.close()

    stats = {'new_this_month': new_this_month, 'expiring_leases': expiring, 'vacant': vacant_count}
    return render_template('tenant.html',
        user=session, tenant=tenant_list, properties=properties,
        vacant_units=[], stats=stats,
    )


@landlord_bp.route('/tenant/add', methods=['POST'])
@login_required
def add_tenant():
    name        = (request.form.get('name') or '').strip()
    phone       = (request.form.get('phone') or '').strip()
    email       = (request.form.get('email') or '').strip().lower()
    property_id = (request.form.get('property_id') or '').strip()
    unit_id_raw = (request.form.get('unit_id') or '').strip()

    if not name or not phone or not email or not property_id or not unit_id_raw:
        flash('Name, phone, email, property, and unit are required.', 'error')
        return redirect(url_for('landlord.tenant'))

    try:
        property_id = int(property_id)
        unit_id     = int(unit_id_raw)
    except ValueError:
        flash('Invalid property or unit.', 'error')
        return redirect(url_for('landlord.tenant'))

    conn, cur, should_close = _get_conn_cur()
    try:
        # Verify property belongs to landlord and get base rent
        cur.execute(
            "SELECT id, base_rent FROM properties WHERE id=%s AND landlord_id=%s LIMIT 1",
            (property_id, session['user_id']),
        )
        prop = cur.fetchone()
        if not prop:
            flash('Property not found.', 'error')
            return redirect(url_for('landlord.tenant'))

        # Validate unit is in the property and available, and get unit_number + rent
        cur.execute("""
            SELECT u.id, u.unit_number, u.tenant_id, u.status, u.rent
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE u.id=%s AND p.id=%s AND p.landlord_id=%s
            LIMIT 1
        """, (unit_id, property_id, session['user_id']))
        unit_row = cur.fetchone()
        if not unit_row:
            flash('Unit not found for that property.', 'error')
            return redirect(url_for('landlord.tenant'))
        if (unit_row.get('tenant_id') or None) is not None:
            flash('That unit is already assigned to another tenant.', 'error')
            return redirect(url_for('landlord.tenant'))
        if (unit_row.get('status') or '') != 'Vacant':
            flash('That unit is not available (must be Vacant).', 'error')
            return redirect(url_for('landlord.tenant'))

        unit_label = unit_row.get('unit_number')
        rent_amount = float(unit_row.get('rent') or 0) or float((prop or {}).get('base_rent') or 0) or 0.0

        # Generate a temporary password for tenant login
        temp_password = 'password123'
        hashed_password = generate_password_hash(temp_password)

        cur.execute("""
            INSERT INTO tenant
                (name, phone, email, unit, amount, status,
                 property_id, unit_id, created_at)
            VALUES (%s, %s, %s, %s, %s, 'Active', %s, %s, NOW())
        """, (name, phone, email, unit_label or None, rent_amount, property_id, unit_id))
        new_id = cur.lastrowid

        # Store password hash (tenant login uses tenant.password)
        cur.execute("UPDATE tenant SET password=%s, role='tenant' WHERE id=%s", (hashed_password, new_id))

        if unit_id:
            cur.execute(
                """
                UPDATE units
                SET tenant_id=%s,
                    status=CASE WHEN status='Maintenance' THEN status ELSE 'Occupied' END
                WHERE id=%s
                """,
                (new_id, unit_id),
            )
        conn.commit()
        flash(f'{name} added. Tenant login email: {email} | Temporary password: {temp_password}', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error adding tenant: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.tenant'))


@landlord_bp.route('/tenant/edit/<int:tenant_id>', methods=['POST'])
@login_required
def edit_tenant(tenant_id):
    name        = (request.form.get('name') or '').strip()
    phone       = (request.form.get('phone') or '').strip()
    email       = (request.form.get('email') or '').strip().lower()
    property_id = (request.form.get('property_id') or '').strip()
    unit_id_raw = (request.form.get('unit_id') or '').strip()

    if not name or not phone or not email or not property_id or not unit_id_raw:
        flash('Name, phone, email, property, and unit are required.', 'error')
        return redirect(url_for('landlord.tenant'))

    try:
        property_id = int(property_id)
        unit_id     = int(unit_id_raw)
    except ValueError:
        flash('Invalid property or unit.', 'error')
        return redirect(url_for('landlord.tenant'))

    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT t.unit_id
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            WHERE t.id=%s AND p.landlord_id=%s
            LIMIT 1
        """, (tenant_id, session['user_id']))
        existing = cur.fetchone()
        if not existing:
            flash('Tenant not found.', 'error')
            return redirect(url_for('landlord.tenant'))
        previous_unit_id = existing.get('unit_id')

        # Verify property belongs to landlord and get base rent
        cur.execute(
            "SELECT id, base_rent FROM properties WHERE id=%s AND landlord_id=%s LIMIT 1",
            (property_id, session['user_id']),
        )
        prop = cur.fetchone()
        if not prop:
            flash('Property not found.', 'error')
            return redirect(url_for('landlord.tenant'))

        # Validate unit belongs to property + landlord, allow current tenant's unit, and get rent
        cur.execute("""
            SELECT u.id, u.unit_number, u.tenant_id, u.status, u.rent
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE u.id=%s AND p.id=%s AND p.landlord_id=%s
            LIMIT 1
        """, (unit_id, property_id, session['user_id']))
        unit_row = cur.fetchone()
        if not unit_row:
            flash('Unit not found for that property.', 'error')
            return redirect(url_for('landlord.tenant'))
        occupied_by = unit_row.get('tenant_id')
        if occupied_by and int(occupied_by) != int(tenant_id):
            flash('That unit is already assigned to another tenant.', 'error')
            return redirect(url_for('landlord.tenant'))
        if not occupied_by and (unit_row.get('status') or '') != 'Vacant':
            flash('That unit is not available (must be Vacant).', 'error')
            return redirect(url_for('landlord.tenant'))

        unit_label = unit_row.get('unit_number')
        rent_amount = float(unit_row.get('rent') or 0) or float((prop or {}).get('base_rent') or 0) or 0.0

        cur.execute("""
            UPDATE tenant
            SET name=%s, phone=%s, email=%s,
                amount=%s, property_id=%s, unit_id=%s
            WHERE id=%s
        """, (name, phone, email, rent_amount, property_id, unit_id, tenant_id))

        # Keep unit label in tenant in sync (some templates show this text)
        cur.execute("UPDATE tenant SET unit=%s WHERE id=%s", (unit_label or None, tenant_id))

        if previous_unit_id and (not unit_id or int(previous_unit_id) != int(unit_id)):
            cur.execute(
                """
                UPDATE units
                SET tenant_id=NULL,
                    status=CASE WHEN status='Occupied' THEN 'Vacant' ELSE status END
                WHERE id=%s AND tenant_id=%s
                """,
                (previous_unit_id, tenant_id),
            )

        if unit_id:
            cur.execute(
                """
                UPDATE units
                SET tenant_id=%s,
                    status=CASE WHEN status='Maintenance' THEN status ELSE 'Occupied' END
                WHERE id=%s
                """,
                (tenant_id, unit_id),
            )
        conn.commit()
        flash('Tenant updated successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating tenant: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.tenant'))


@landlord_bp.route('/tenant/<int:tenant_id>/delete', methods=['POST'])
@login_required
def delete_tenant(tenant_id):
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("SELECT id, name, unit_id FROM tenant WHERE id=%s", (tenant_id,))
        t = cur.fetchone()
        if not t:
            flash('Tenant not found.', 'error')
            return redirect(url_for('landlord.tenant'))

        if t.get('unit_id'):
            cur.execute(
                "UPDATE units SET status='Vacant', tenant_id=NULL WHERE id=%s AND tenant_id=%s",
                (t['unit_id'], tenant_id)
            )
        cur.execute("DELETE FROM tenant WHERE id=%s", (tenant_id,))
        conn.commit()
        flash(f'{t["name"]} removed successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error removing tenant: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.tenant'))


# ----------------------
# MAINTENANCE
# ----------------------

@landlord_bp.route('/maintenance')
@login_required
def maintenance():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        # Use maintenance_requests.property_id directly (it exists in schema)
        cur.execute("""
            SELECT m.id, m.title, m.description, m.priority, m.status,
                   m.unit_id, m.assigned_to,
                   m.tenant_id,
                   p.name AS property_name,
                   u.unit_number,
                   COALESCE(t.name, '-') AS tenant_name,
                   sp.first_name AS sp_first, sp.last_name AS sp_last,
                   m.created_at, m.updated_at
            FROM maintenance_requests m
            LEFT JOIN properties p ON p.id = m.property_id
            LEFT JOIN units u      ON u.id = m.unit_id
            LEFT JOIN tenant t    ON t.unit_id = m.unit_id
            LEFT JOIN service_provider sp ON sp.id = m.assigned_to
            WHERE p.landlord_id = %s
            ORDER BY FIELD(m.priority,'High','Medium','Low'), m.created_at DESC
        """, (landlord_id,))
        tickets = [dict(r) for r in cur.fetchall()]
        for t in tickets:
            fn = (t.get('sp_first') or '').strip()
            ln = (t.get('sp_last') or '').strip()
            t['assigned_name'] = f"{fn} {ln}".strip() or None

        cur.execute("""
            SELECT id, first_name, last_name FROM service_provider
            WHERE LOWER(status) = 'active' OR status IS NULL
            ORDER BY first_name, last_name
        """)
        service_providers = [dict(r) for r in cur.fetchall()]
        for sp in service_providers:
            sp['full_name'] = f"{sp.get('first_name','')} {sp.get('last_name','')}".strip()

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
    finally:
        cur.close()
        if should_close:
            conn.close()

    return render_template('maintenance.html',
        user=session, tickets=tickets,
        service_providers=service_providers,
        open_count=open_count, urgent_count=urgent,
        in_progress_count=in_progress, resolved_this_month=resolved_this_month,
    )


@landlord_bp.route('/maintenance/<int:ticket_id>/assign', methods=['POST'])
@login_required
def landlord_assign_maintenance_ticket(ticket_id):
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    provider_id_raw = (request.form.get('provider_id') or '').strip()
    try:
        provider_id = int(provider_id_raw) if provider_id_raw else None
    except ValueError:
        provider_id = None

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            UPDATE maintenance_requests m
            JOIN properties p ON p.id = m.property_id
            SET m.assigned_to=%s, m.status='In Progress', m.updated_at=NOW()
            WHERE m.id=%s AND p.landlord_id=%s
        """, (provider_id, ticket_id, landlord_id))
        conn.commit()
        flash('Service provider assigned.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.maintenance'))



@landlord_bp.route('/maintenance/<int:ticket_id>/update', methods=['POST'])
@login_required
def landlord_update_maintenance_ticket(ticket_id):
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    new_status = request.form.get('status', '').strip()
    if new_status not in {'Open', 'Seen', 'In Progress', 'Resolved', 'Closed'}:
        flash('Invalid status.', 'error')
        return redirect(url_for('landlord.maintenance'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        # Use property_id directly on maintenance_requests
        cur.execute("""
            UPDATE maintenance_requests m
            JOIN properties p ON p.id = m.property_id
            SET m.status=%s, m.updated_at=NOW()
            WHERE m.id=%s AND p.landlord_id=%s
        """, (new_status, ticket_id, landlord_id))
        conn.commit()
        flash('Ticket updated.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.maintenance'))


# ----------------------
# BILLS OVERVIEW
# ----------------------

@landlord_bp.route('/landlord/bills')
@login_required
def landlord_bills():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    status_filter = (request.args.get('status') or '').strip()
    conn, cur, should_close = _get_conn_cur()
    try:
        sql = """
            SELECT b.id, b.bill_type, b.amount, b.amount_due, b.due_date,
                   b.status, b.month, b.created_at,
                   t.id AS tenant_id, t.name AS tenant_name,
                   u.unit_number, p.name AS property_name
            FROM bills b
            JOIN tenant t     ON t.id = b.tenant_id
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE p.landlord_id = %s
        """
        params = [landlord_id]
        if status_filter:
            sql += " AND LOWER(b.status) = %s"
            params.append(status_filter.lower())
        sql += " ORDER BY b.created_at DESC"
        cur.execute(sql, params)
        bills = [dict(r) for r in cur.fetchall()]

        total_billed = sum(float(b.get('amount') or 0) for b in bills)
        total_paid   = sum(float(b.get('amount') or 0) for b in bills if (b.get('status') or '').lower() == 'paid')
        total_pending = sum(float(b.get('amount') or 0) for b in bills if (b.get('status') or '').lower() != 'paid')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return render_template('landlord_bills.html',
        user=session, bills=bills,
        total_billed=total_billed, total_paid=total_paid, total_pending=total_pending,
        status_filter=status_filter,
    )


@landlord_bp.route('/landlord/bills/<int:bill_id>/delete', methods=['POST'])
@login_required
def landlord_delete_bill(bill_id):
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            DELETE b FROM bills b
            JOIN tenant t ON t.id = b.tenant_id
            JOIN properties p ON p.id = t.property_id
            WHERE b.id = %s AND p.landlord_id = %s
        """, (bill_id, landlord_id))
        conn.commit()
        flash('Bill deleted.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()
    return redirect(url_for('landlord.landlord_bills'))


# ----------------------
# REPORTS
# ----------------------

@landlord_bp.route('/reports')
@login_required
def reports():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    from datetime import date as _date
    import blueprints.reports as reports_mod

    today = _date.today()
    year = today.year
    month = today.month

    # Last 6 months (same year fallback if early months)
    months = list(range(max(1, month - 5), month + 1))

    monthly_rows = reports_mod._get_income_expense_monthly(year, months)
    property_rows = reports_mod._get_occupancy_by_property(year, month)

    income_m = (monthly_rows[-1]["income"] if monthly_rows else 0)  # current month
    expenses_m = (monthly_rows[-1]["expenses"] if monthly_rows else 0)
    net_m = (monthly_rows[-1]["net"] if monthly_rows else 0)

    # YTD income
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN LOWER(pay.status)='paid' THEN pay.Amount ELSE 0 END),0) AS ytd_income
            FROM payments pay
            JOIN properties p ON p.id = pay.property_id
            WHERE p.landlord_id = %s
              AND pay.paid_on >= %s
              AND pay.paid_on < %s
            """,
            (session["user_id"], _date(year, 1, 1), _date(year + 1, 1, 1)),
        )
        ytd_income = float((cur.fetchone() or {}).get("ytd_income") or 0)
    finally:
        cur.close()
        if should_close:
            conn.close()

    kpis = {
        "month_label": today.strftime("%b"),
        "income_month": income_m,
        "expenses_month": expenses_m,
        "net_month": net_m,
        "ytd_income": ytd_income,
    }

    return render_template(
        'reports.html',
        user=session,
        kpis=kpis,
        monthly_rows=monthly_rows,
        property_rows=property_rows,
        year=year,
        month=month,
    )


# ----------------------
# SEND NOTICES
# ----------------------

@landlord_bp.route('/send-notices')
@login_required
def send_notices():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("SELECT id, name FROM properties WHERE landlord_id=%s ORDER BY name", (landlord_id,))
        properties = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT t.id, t.name, t.email, t.phone, t.property_id,
                   u.unit_number,
                   p.name AS property_name
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE p.landlord_id=%s
            ORDER BY p.name, u.unit_number, t.name
        """, (landlord_id,))
        tenant = [dict(r) for r in cur.fetchall()]

        # notices has title + message
        cur.execute("""
            SELECT id, property_id, title, message, type, created_at AS sent_at
            FROM notices WHERE sender_id=%s
            ORDER BY created_at DESC LIMIT 20
        """, (landlord_id,))
        notices = [dict(r) for r in cur.fetchall()]

        today = date.today()
        month_start = today.replace(day=1)
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM notices
            WHERE sender_id=%s AND created_at >= %s
        """, (landlord_id, month_start))
        sent_this_month = int((cur.fetchone() or {}).get('cnt') or 0)
        last_sent = notices[0]['sent_at'] if notices else None
    finally:
        cur.close()
        if should_close:
            conn.close()

    return render_template('send_notices.html',
        user=session, tenant=tenant, properties=properties,
        notices=notices, sent_this_month=sent_this_month,
        recipients_total=len(tenant), last_sent=last_sent,
    )


@landlord_bp.route('/send-notices/send', methods=['POST'])
@login_required
def landlord_send_notice():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    subject     = (request.form.get('subject') or '').strip()
    body        = (request.form.get('message') or '').strip()
    notice_type = (request.form.get('type') or 'normal').strip()
    via         = set(request.form.getlist('via'))

    tenant_ids = [t for t in request.form.getlist('tenant_ids') if str(t).strip()]
    if not tenant_ids:
        flash('Select at least one recipient.', 'error')
        return redirect(url_for('landlord.send_notices'))
    if not body and not subject:
        flash('Message cannot be empty.', 'error')
        return redirect(url_for('landlord.send_notices'))

    message = f"{subject}\n\n{body}".strip() if subject else body
    title   = subject or 'Notice'

    conn, cur, should_close = _get_conn_cur()
    try:
        placeholders = ",".join(["%s"] * len(tenant_ids))
        cur.execute(f"""
            SELECT DISTINCT t.property_id
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            WHERE t.id IN ({placeholders}) AND p.landlord_id=%s
        """, (*tenant_ids, landlord_id))
        property_ids = [r['property_id'] for r in cur.fetchall() if r.get('property_id')]

        if not property_ids:
            flash('Selected recipients are not valid for your account.', 'error')
            return redirect(url_for('landlord.send_notices'))

        # notices: landlord_id, sender_id, property_id, title, message, type
        for pid in property_ids:
            cur.execute("""
                INSERT INTO notices
                    (landlord_id, sender_id, property_id, title, message, type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (landlord_id, landlord_id, pid, title, message, notice_type))

        conn.commit()
        via_label = ", ".join(sorted(via)) if via else "in_app"
        flash(f'Notice sent ({via_label}) for {len(tenant_ids)} recipient(s).', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error sending notice: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.send_notices'))


# ----------------------
# LEASE AGREEMENTS
# ----------------------

@landlord_bp.route('/lease-agreements')
@login_required
def lease_agreements():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT l.*,
                   p.name AS property_name,
                   u.unit_number AS unit_number_live,
                   t.name AS tenant_name_live
            FROM leases l
            LEFT JOIN properties p ON p.id = l.property_id
            LEFT JOIN units u      ON u.id = l.unit_id
            LEFT JOIN tenant t    ON t.id = l.tenant_id
            WHERE l.landlord_id=%s
            ORDER BY l.created_at DESC
        """, (landlord_id,))
        leases = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT t.id, t.name, t.email, t.phone, t.property_id,
                   u.unit_number,
                   p.name AS property_name
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            LEFT JOIN units u ON u.id = t.unit_id
            WHERE p.landlord_id=%s
            ORDER BY p.name, u.unit_number, t.name
        """, (landlord_id,))
        tenant = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT u.id, u.unit_number, u.rent, u.property_id,
                   p.name AS property_name, u.status
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE p.landlord_id=%s
            ORDER BY p.name, u.unit_number
        """, (landlord_id,))
        unit_list = [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        if should_close:
            conn.close()

    today  = date.today()
    in_90  = today + timedelta(days=90)

    def _as_date(val):
        if not val:
            return None
        return val.date() if hasattr(val, 'date') else val

    active = expiring_90 = expired = pending = 0
    for l in leases:
        st    = (l.get('status') or '').lower()
        end_d = _as_date(l.get('end_date'))
        if st == 'active':
            active += 1
            if end_d and today <= end_d <= in_90:
                expiring_90 += 1
            if end_d and end_d < today:
                expired += 1
        elif st in {'draft', 'pending signature', 'pending_signature'}:
            pending += 1

    stats = {'active': active, 'expiring_90': expiring_90, 'expired': expired, 'pending': pending}
    return render_template('lease_agreements.html',
        user=session, leases=leases, tenant=tenant, units=unit_list, stats=stats,
    )


@landlord_bp.route('/lease-agreements/create', methods=['POST'])
@login_required
def create_lease_agreement():
    if (session.get('role') or '').lower() != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id    = session['user_id']
    tenant_id      = request.form.get('tenant_id', '').strip()
    unit_id        = request.form.get('unit_id', '').strip()
    start_date     = request.form.get('start_date') or None
    end_date       = request.form.get('end_date') or None
    rent_amount    = request.form.get('rent_amount', '0').strip()
    deposit_amount = request.form.get('deposit_amount', '0').strip()
    terms          = (request.form.get('terms') or '').strip()

    try:
        tenant_id_int      = int(tenant_id) if tenant_id else None
        unit_id_int        = int(unit_id) if unit_id else None
        rent_amount_f      = float(rent_amount or 0)
        deposit_amount_f   = float(deposit_amount or 0)
    except ValueError:
        flash('Invalid lease values.', 'error')
        return redirect(url_for('landlord.lease_agreements'))

    if not tenant_id_int or not unit_id_int:
        flash('Select a tenant and a unit.', 'error')
        return redirect(url_for('landlord.lease_agreements'))

    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT t.id, t.name, t.email, t.phone, t.property_id
            FROM tenant t
            JOIN properties p ON p.id = t.property_id
            WHERE t.id=%s AND p.landlord_id=%s
        """, (tenant_id_int, landlord_id))
        tenant = cur.fetchone()
        if not tenant:
            flash('Tenant not found for your account.', 'error')
            return redirect(url_for('landlord.lease_agreements'))

        cur.execute("""
            SELECT u.id, u.unit_number, u.rent, u.property_id
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE u.id=%s AND p.landlord_id=%s
        """, (unit_id_int, landlord_id))
        unit = cur.fetchone()
        if not unit:
            flash('Unit not found for your account.', 'error')
            return redirect(url_for('landlord.lease_agreements'))

        sign_token  = secrets.token_urlsafe(24)
        property_id = unit.get('property_id') or tenant.get('property_id')

        if not terms:
            terms = (
                "Standard lease terms: rent due by the 5th of each month. "
                "Tenant responsible for utilities unless otherwise agreed. "
                "Maintenance requests must be reported via the portal."
            )

        cur.execute("""
            INSERT INTO leases (
                landlord_id, property_id, unit_id, tenant_id,
                tenant_name, tenant_email, tenant_phone,
                unit_number, rent_amount, deposit_amount,
                start_date, end_date, terms,
                status, sign_token, created_at
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                'Pending Signature', %s, NOW()
            )
        """, (
            landlord_id, property_id, unit_id_int, tenant_id_int,
            tenant.get('name'), tenant.get('email'), tenant.get('phone'),
            unit.get('unit_number'), rent_amount_f, deposit_amount_f,
            start_date, end_date, terms, sign_token,
        ))
        conn.commit()
        flash('Lease created. Share the signing link with the tenant.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error creating lease: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('landlord.lease_agreements'))


@landlord_bp.route('/lease-agreements/<int:lease_id>/delete', methods=['POST'])
@login_required
def delete_lease(lease_id):
    if (session.get('role') or '').lower() != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute(
            "DELETE FROM leases WHERE id=%s AND landlord_id=%s",
            (lease_id, landlord_id)
        )
        conn.commit()
        flash('Lease deleted.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting lease: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()
    return redirect(url_for('landlord.lease_agreements'))


@landlord_bp.route('/lease-agreements/sign/<token>', methods=['GET', 'POST'])
def sign_lease_agreement(token):
    token = (token or '').strip()
    if not token:
        return "Invalid token", 400

    conn, cur, should_close = _get_conn_cur()
    try:
        cur.execute("""
            SELECT l.*,
                   p.name AS property_name,
                   u.unit_number AS unit_number_live
            FROM leases l
            LEFT JOIN properties p ON p.id = l.property_id
            LEFT JOIN units u      ON u.id = l.unit_id
            WHERE l.sign_token=%s LIMIT 1
        """, (token,))
        lease = cur.fetchone()
        if not lease:
            return "Lease not found", 404

        if request.method == 'POST':
            signed_name = (request.form.get('signed_name') or '').strip()
            if not signed_name:
                flash('Enter your full name to sign.', 'error')
                return render_template('lease_sign.html', lease=lease)
            try:
                cur.execute("""
                    UPDATE leases
                    SET signed_name=%s, signed_at=NOW(), signed_ip=%s,
                        status='Active', updated_at=NOW()
                    WHERE id=%s
                """, (signed_name, request.remote_addr, lease['id']))

                if lease.get('tenant_id'):
                    cur.execute("""
                        UPDATE tenant
                        SET amount=%s, status='Active'
                        WHERE id=%s
                    """, (lease.get('rent_amount') or 0, lease.get('tenant_id')))

                if lease.get('unit_id'):
                    cur.execute(
                        "UPDATE units SET status='Occupied' WHERE id=%s",
                        (lease.get('unit_id'),)
                    )
                conn.commit()
                return render_template('lease_sign.html', lease=lease, signed=True)
            except Exception as e:
                conn.rollback()
                flash(f'Error signing lease: {str(e)}', 'error')

        return render_template('lease_sign.html', lease=lease)
    finally:
        cur.close()
        if should_close:
            conn.close()
