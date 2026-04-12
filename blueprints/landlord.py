import os
from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify, current_app
from extensions import mysql
from helpers import login_required, save_property_image, serialize_units, sync_unit_count, get_landlord_stats

landlord_bp = Blueprint('landlord', __name__)


# -------------------------
# LANDLORD DASHBOARD
# -------------------------
@landlord_bp.route('/landlord_dashboard')
def landlord_dashboard():
    landlord_id = session.get('user_id')
    cursor = mysql.connection.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM properties")
    result = cursor.fetchone()
    total_properties = result['total'] if result else 0

    cursor.execute("SELECT COUNT(*) AS total FROM units")
    result = cursor.fetchone()
    total_units = result['total'] if result else 0

    cursor.execute("SELECT COUNT(*) AS total FROM units WHERE status='occupied'")
    result = cursor.fetchone()
    occupied = result['total'] if result else 0

    occupancy_rate = int((occupied / total_units) * 100) if total_units > 0 else 0

    cursor.execute("SELECT SUM(Amount) AS total FROM payments WHERE status='Paid'")
    result = cursor.fetchone()
    rent_collected = result['total'] if result and result['total'] is not None else 0

    cursor.execute("SELECT SUM(Amount) AS total FROM payments WHERE status!='Paid'")
    result = cursor.fetchone()
    rent_outstanding = result['total'] if result and result['total'] is not None else 0

    cursor.execute("SELECT name, unit, amount, status FROM tenants")
    rows = cursor.fetchall()
    tenant = [{"name": r['name'], "unit": r['unit'], "amount": r['amount']} for r in rows]

    cursor.execute("""
        SELECT u.id, u.unit_number, u.rent AS rent_amount, u.status, u.property_id
        FROM units u ORDER BY u.id DESC LIMIT 5
    """)
    properties = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT userid, Amount, status, `full name` AS tenant_name, `phone no` AS phone
        FROM payments ORDER BY userid DESC LIMIT 5
    """)
    recent_payments = []
    for row in cursor.fetchall():
        p = dict(row)
        p['amount'] = p.get('Amount', 0)
        p['date']   = p.get('status', 'N/A')
        recent_payments.append(p)

    cursor.close()

    return render_template(
        "landlord_dashboard.html",
        user=session,
        total_properties=total_properties,
        total_units=total_units,
        occupancy_rate=occupancy_rate,
        rent_collected=rent_collected,
        rent_outstanding=rent_outstanding,
        tenant=tenant,
        properties=properties,
        recent_payments=recent_payments
    )


# -------------------------
# PROFILE
# -------------------------
@landlord_bp.route('/profile')
@login_required
def profile():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))
    return render_template('profile.html', user=session)


@landlord_bp.route('/rent-collection')
@login_required
def rent_collection():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    cur = mysql.connection.cursor()

    # All payments joined with properties for this landlord
    cur.execute("""
        SELECT p.userid, p.`full name` AS full_name, p.`phone no` AS phone,
               p.Amount AS amount, p.status, p.unit, p.method,
               p.reference, p.paid_on, p.month, p.property_id,
               pr.name AS property_name
        FROM payments p
        LEFT JOIN properties pr ON pr.id = p.property_id
        WHERE pr.landlord_id = %s OR p.property_id IS NULL
        ORDER BY p.userid DESC
    """, (landlord_id,))
    payments = []
    for row in cur.fetchall():
        r = dict(row)
        r['amount'] = float(r.get('amount') or 0)
        r['paid_on'] = str(r['paid_on']) if r.get('paid_on') else '—'
        r['method']  = r.get('method') or '—'
        r['unit']    = r.get('unit') or '—'
        r['property_name'] = r.get('property_name') or '—'
        r['status']  = r.get('status') or 'Pending'
        payments.append(r)

    # KPI calculations
    paid_payments     = [p for p in payments if p['status'] == 'Paid']
    pending_payments  = [p for p in payments if p['status'] == 'Pending']
    overdue_payments  = [p for p in payments if p['status'] == 'Overdue']
    total_collected   = sum(p['amount'] for p in paid_payments)
    total_outstanding = sum(p['amount'] for p in pending_payments + overdue_payments)
    total_units       = len(payments)
    units_paid        = len(paid_payments)
    collection_rate   = int((units_paid / total_units) * 100) if total_units > 0 else 0

    # Tenants for the Record Payment dropdown
    cur.execute("SELECT id, name, unit FROM tenants ORDER BY name")
    tenants = [dict(r) for r in cur.fetchall()]

    # Properties for filter dropdown
    cur.execute("SELECT id, name FROM properties WHERE landlord_id = %s", (landlord_id,))
    properties = [dict(r) for r in cur.fetchall()]

    cur.close()

    stats = {
        'collected':       total_collected,
        'outstanding':     total_outstanding,
        'units_paid':      units_paid,
        'total_units':     total_units,
        'collection_rate': collection_rate,
        'overdue_count':   len(overdue_payments),
    }

    return render_template('rent_collection.html',
        user=session,
        payments=payments,
        tenants=tenants,
        properties=properties,
        stats=stats
    )


@landlord_bp.route('/rent-collection/record', methods=['POST'])
@login_required
def record_payment():
    tenant_id  = request.form.get('tenant_id', '').strip()
    amount     = request.form.get('amount', '0').strip()
    method     = request.form.get('method', 'Cash').strip()
    reference  = request.form.get('reference', '').strip()
    paid_on    = request.form.get('paid_on') or None
    unit       = request.form.get('unit', '').strip()
    full_name  = request.form.get('full_name', '').strip()
    phone      = request.form.get('phone', '').strip()
    property_id = request.form.get('property_id', '').strip()

    try:
        amount = float(amount)
        property_id = int(property_id) if property_id else None
    except ValueError:
        flash('Invalid amount or property.', 'error')
        return redirect(url_for('landlord.rent_collection'))

    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO payments (`full name`, `phone no`, Amount, status,
                                  unit, method, reference, paid_on, property_id, month)
            VALUES (%s, %s, %s, 'Paid', %s, %s, %s, %s, %s,
                    DATE_FORMAT(NOW(), '%%M %%Y'))
        """, (full_name, phone, amount, unit, method, reference, paid_on, property_id))
        mysql.connection.commit()
        flash(f'Payment of KES {amount:,.0f} recorded for {full_name}!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error recording payment: {str(e)}', 'error')
    finally:
        cur.close()

    return redirect(url_for('landlord.rent_collection'))


@landlord_bp.route('/rent-collection/update-status/<int:payment_id>', methods=['POST'])
@login_required  
def update_payment_status(payment_id):
    status = request.form.get('status', 'Paid')
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            UPDATE payments SET status=%s, paid_on=CURDATE() 
            WHERE userid=%s
        """, (status, payment_id))
        mysql.connection.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()


# -------------------------
# GET UNITS (JSON)
# -------------------------
@landlord_bp.route('/properties/<int:property_id>/units')
@login_required
def get_units(property_id):
    if session.get('role') != 'landlord':
        return jsonify({'error': 'Unauthorized'}), 403

    landlord_id = session['user_id']
    cur = mysql.connection.cursor()

    cur.execute(
        "SELECT id FROM properties WHERE id = %s AND landlord_id = %s",
        (property_id, landlord_id)
    )
    if not cur.fetchone():
        cur.close()
        return jsonify({'error': 'Not found'}), 404

    cur.execute("""
        SELECT u.id, u.unit_number, u.floor, u.type,
               u.rent, u.status,
               usr.name AS tenant_name
        FROM units u
        LEFT JOIN users usr ON usr.id = u.tenant_id
        WHERE u.property_id = %s
        ORDER BY u.unit_number
    """, (property_id,))
    rows = cur.fetchall()
    cur.close()

    return jsonify({'units': serialize_units(rows)})


# -------------------------
# ADD UNIT
# -------------------------
@landlord_bp.route('/units/add', methods=['POST'])
@login_required
def add_unit():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landlord.properties'))

    landlord_id = session['user_id']
    property_id = request.form.get('property_id', '').strip()
    unit_number = request.form.get('unit_number', '').strip()
    unit_type   = request.form.get('type', '1 Bedroom')

    try:
        floor = int(request.form.get('floor') or 1)
    except ValueError:
        floor = 1

    try:
        rent = float(request.form.get('rent') or 0)
    except ValueError:
        rent = 0.0

    if not property_id or not unit_number:
        flash('Property and unit number are required.', 'error')
        return redirect(url_for('landlord.properties'))

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id FROM properties WHERE id = %s AND landlord_id = %s",
        (property_id, landlord_id)
    )
    if not cur.fetchone():
        cur.close()
        flash('Property not found.', 'error')
        return redirect(url_for('landlord.properties'))

    cur.execute(
        "SELECT id FROM units WHERE property_id = %s AND unit_number = %s",
        (property_id, unit_number)
    )
    if cur.fetchone():
        cur.close()
        flash(f'Unit {unit_number} already exists in this property.', 'error')
        return redirect(url_for('landlord.properties'))

    cur.execute("""
        INSERT INTO units (property_id, unit_number, floor, type, rent)
        VALUES (%s, %s, %s, %s, %s)
    """, (property_id, unit_number, floor, unit_type, rent))
    mysql.connection.commit()

    sync_unit_count(cur, property_id)
    mysql.connection.commit()
    cur.close()

    flash(f'Unit {unit_number} added successfully!', 'success')
    return redirect(url_for('landlord.properties'))


# -------------------------
# DELETE UNIT
# -------------------------
@landlord_bp.route('/units/delete/<int:unit_id>', methods=['POST'])
@login_required
def delete_unit(unit_id):
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landlord.properties'))

    landlord_id = session['user_id']
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT u.id, u.unit_number, u.property_id
        FROM units u
        JOIN properties p ON p.id = u.property_id
        WHERE u.id = %s AND p.landlord_id = %s
    """, (unit_id, landlord_id))
    unit = cur.fetchone()

    if not unit:
        cur.close()
        flash('Unit not found.', 'error')
        return redirect(url_for('landlord.properties'))

    property_id = unit['property_id']
    cur.execute("DELETE FROM units WHERE id = %s", (unit_id,))
    mysql.connection.commit()

    sync_unit_count(cur, property_id)
    mysql.connection.commit()
    cur.close()

    flash(f'Unit {unit["unit_number"]} deleted.', 'success')
    return redirect(url_for('landlord.properties'))


# -------------------------
# TENANTS
# -------------------------
@landlord_bp.route('/tenant')
@login_required
def tenant():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))

    landlord_id = session['user_id']
    cur = mysql.connection.cursor()

    # Tenant list — join properties to get real property name
    cur.execute("""
        SELECT t.id, t.name, t.email, t.phone, t.unit, t.amount, t.status,
               t.lease_start, t.lease_end, t.property_id, t.created_at,
               p.name AS property_name
        FROM tenants t
        LEFT JOIN properties p ON p.id = t.property_id
        WHERE t.id IS NOT NULL AND t.id != ''
        ORDER BY t.created_at DESC
    """)
    tenant_list = []
    for row in cur.fetchall():
        t = dict(row)
        # Skip any row that somehow has no integer id
        if not t.get('id'):
            continue
        t['id']            = int(t['id'])
        t['rent']          = float(t.get('amount') or 0)
        t['unit_number']   = t.get('unit') or '—'
        t['property_name'] = t.get('property_name') or '—'
        t['lease_start']   = str(t['lease_start'])[:10] if t.get('lease_start') else '—'
        t['lease_end']     = str(t['lease_end'])[:10]   if t.get('lease_end')   else '—'
        t['status']        = t.get('status') or 'Active'
        t['status_color']  = (
            'active'   if t['status'] == 'Active'   else
            'expiring' if t['status'] == 'Expiring' else
            'inactive'
        )
        tenant_list.append(t)

    # Properties for Add/Edit dropdowns
    cur.execute("""
        SELECT id, name FROM properties
        WHERE landlord_id = %s ORDER BY name
    """, (landlord_id,))
    properties = [dict(r) for r in cur.fetchall()]

    # Vacant units
    cur.execute("""
        SELECT u.id, u.unit_number, p.name AS property_name, u.rent
        FROM units u
        JOIN properties p ON p.id = u.property_id
        WHERE u.status = 'Vacant' AND p.landlord_id = %s
        ORDER BY p.name, u.unit_number
        LIMIT 20
    """, (landlord_id,))
    vacant_units = [dict(r) for r in cur.fetchall()]

    # KPI stats
    today       = date.today()
    month_start = today.replace(day=1)
    next_60     = today + timedelta(days=60)

    cur.execute("SELECT COUNT(*) AS cnt FROM tenants WHERE created_at >= %s", (month_start,))
    new_this_month = (cur.fetchone() or {}).get('cnt', 0)

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM tenants WHERE lease_end BETWEEN %s AND %s",
        (today, next_60)
    )
    expiring = (cur.fetchone() or {}).get('cnt', 0)

    cur.execute("""
        SELECT COUNT(*) AS cnt FROM units u
        JOIN properties p ON u.property_id = p.id
        WHERE p.landlord_id = %s AND u.status = 'Vacant'
    """, (landlord_id,))
    vacant_count = (cur.fetchone() or {}).get('cnt', 0)

    cur.close()

    stats = {
        'new_this_month':  new_this_month,
        'expiring_leases': expiring,
        'vacant':          vacant_count,
    }

    return render_template('tenant.html',
        user=session,
        tenant=tenant_list,
        properties=properties,
        vacant_units=vacant_units,
        stats=stats
    )


@landlord_bp.route('/tenants/add', methods=['POST'])
@login_required
def add_tenant():
    name        = request.form.get('name', '').strip()
    phone       = request.form.get('phone', '').strip()
    email       = request.form.get('email', '').strip()
    unit        = request.form.get('unit', '').strip()
    amount      = request.form.get('amount', '0').strip()
    property_id = request.form.get('property_id', '').strip()
    lease_start = request.form.get('lease_start') or None
    lease_end   = request.form.get('lease_end')   or None

    if not name or not phone or not unit or not amount:
        flash('Name, phone, unit, and rent are required.', 'error')
        return redirect(url_for('landlord.tenant'))

    # Convert property_id to int or None
    try:
        property_id = int(property_id) if property_id else None
    except ValueError:
        property_id = None

    try:
        amount = float(amount)
    except ValueError:
        flash('Invalid rent amount.', 'error')
        return redirect(url_for('landlord.tenant'))

    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO tenants (name, phone, email, unit, amount, status,
                                 property_id, lease_start, lease_end, created_at)
            VALUES (%s, %s, %s, %s, %s, 'Active', %s, %s, %s, NOW())
        """, (name, phone, email, unit, amount, property_id, lease_start, lease_end))
        mysql.connection.commit()
        flash(f'{name} added successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error adding tenant: {str(e)}', 'error')
    finally:
        cur.close()

    return redirect(url_for('landlord.tenant'))


# -------------------------
# EDIT TENANT
# -------------------------
@landlord_bp.route('/tenants/edit/<int:tenant_id>', methods=['POST'])
@login_required
def edit_tenant(tenant_id):
    name        = request.form.get('name', '').strip()
    phone       = request.form.get('phone', '').strip()
    email       = request.form.get('email', '').strip()
    unit        = request.form.get('unit', '').strip()
    amount      = request.form.get('amount', '0')
    property_id = request.form.get('property_id', '').strip()
    lease_start = request.form.get('lease_start') or None
    lease_end   = request.form.get('lease_end')   or None

    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            UPDATE tenants
            SET name=%s, phone=%s, email=%s, unit=%s, amount=%s,
                property_id=%s, lease_start=%s, lease_end=%s
            WHERE id=%s
        """, (name, phone, email, unit, float(amount), property_id, lease_start, lease_end, tenant_id))
        mysql.connection.commit()
        flash('Tenant updated successfully.', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error updating tenant: {str(e)}', 'error')
    finally:
        cur.close()

    return redirect(url_for('landlord.tenant'))


# -------------------------
# DELETE TENANT
# -------------------------
@landlord_bp.route('/tenants/<int:tenant_id>/delete', methods=['POST'])
@login_required
def delete_tenant(tenant_id):
    cur = mysql.connection.cursor()
    try:
        cur.execute("SELECT id, name FROM tenants WHERE id = %s", (tenant_id,))
        t = cur.fetchone()
        if not t:
            flash('Tenant not found.', 'error')
            return redirect(url_for('landlord.tenant'))

        cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        mysql.connection.commit()
        flash(f'{t["name"]} removed successfully.', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error removing tenant: {str(e)}', 'error')
    finally:
        cur.close()

    return redirect(url_for('landlord.tenant'))


# -------------------------
# MAINTENANCE
# -------------------------
@landlord_bp.route('/maintenance')
@login_required
def maintenance():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))
    return render_template('maintenance.html', user=session)


# -------------------------
# REPORTS
# -------------------------
@landlord_bp.route('/reports')
@login_required
def reports():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))
    return render_template('reports.html', user=session)


# -------------------------
# SEND NOTICES
# -------------------------
@landlord_bp.route('/send-notices')
@login_required
def send_notices():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))
    return render_template('send_notices.html', user=session)


# -------------------------
# LEASE AGREEMENTS
# -------------------------
@landlord_bp.route('/lease-agreements')
@login_required
def lease_agreements():
    if session.get('role') != 'landlord':
        flash('Unauthorized', 'error')
        return redirect(url_for('landing'))
    return render_template('lease_agreements.html', user=session)