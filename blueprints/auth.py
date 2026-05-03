from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import mysql, get_db_connection, get_conn_and_cursor
from helpers import login_required

auth_bp = Blueprint('auth', __name__)


# -------------------------
# LOGIN
# -------------------------
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('All fields are required', 'error')
            return redirect(url_for('auth.login'))

        # Get connection (use fallback if mysql.connection is None)
        conn = mysql.connection if mysql.connection is not None else get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()

        if not user:
            flash('Invalid email', 'error')
            return redirect(url_for('auth.login'))

        if check_password_hash(user['password'], password):
            # Store session data
            session['user_id'] = user['id']
            session['user_name'] = user['first_name'] + ' ' + user['last_name']
            session['user_email'] = user['email']
            session['role'] = user['role']

            flash(f"Welcome {user['first_name']}!", 'success')

            # Redirect based on role
            if user['role'] == 'tenant':
                return redirect(url_for('tenant.tenant_dashboard'))
            elif user['role'] == 'landlord':
                return redirect(url_for('landlord.landlord_dashboard'))
            elif user['role'] == 'service_provider':
                return redirect(url_for('service.service_dashboard'))
            elif user['role'] == 'agent':
                return redirect(url_for('agent.agent_dashboard'))


        else:
            flash('Wrong password', 'error')
            return redirect(url_for('auth.login'))

    return render_template('login.html')


# -------------------------
# REGISTER
# -------------------------
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        role = request.form.get('role')

        if not all([first_name, last_name, email, password, confirm, role]):
            flash('All fields required', 'error')
            return redirect(url_for('auth.register'))

        if password != confirm:
            flash('Passwords do not match', 'error')
            return redirect(url_for('auth.register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return redirect(url_for('auth.register'))

        conn = mysql.connection if mysql.connection is not None else get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            flash('Email already exists', 'error')
            cur.close()
            return redirect(url_for('auth.register'))

        hashed_password = generate_password_hash(password)

        cur.execute(
            "INSERT INTO users (first_name, last_name, email, password, role) VALUES (%s, %s, %s, %s, %s)",
            (first_name, last_name, email, hashed_password, role)
        )
        conn.commit()
        cur.close()

        flash('Registered successfully. Please login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


# -------------------------
# LOGOUT
# -------------------------
@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('auth.login'))


# -------------------------
# SETTINGS
# -------------------------
@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        user_id = session.get('user_id')
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        tenant_property_id_raw = (request.form.get('tenant_property_id') or '').strip()
        tenant_unit_id_raw = (request.form.get('tenant_unit_id') or '').strip()

        if full_name and email:
            conn, cur, should_close = get_conn_and_cursor()
            try:
                # Keep this compatible with existing DBs that store either (first_name,last_name) or name
                try:
                    cur.execute(
                        "UPDATE users SET name=%s, email=%s WHERE id=%s",
                        (full_name, email, user_id)
                    )
                    conn.commit()
                except Exception:
                    # Fallback to first_name/last_name schema
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    parts = [p for p in (full_name or "").split(" ") if p.strip()]
                    first_name = parts[0] if parts else full_name
                    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                    cur.execute(
                        "UPDATE users SET first_name=%s, last_name=%s, email=%s WHERE id=%s",
                        (first_name, last_name, email, user_id)
                    )
                    conn.commit()
            finally:
                cur.close()
                if should_close:
                    conn.close()

            # Update session so topbar name refreshes
            session['user_name'] = full_name
            session['user_email'] = email

            flash('Settings saved successfully', 'success')
        else:
            flash('Name and email are required', 'error')

        # Tenant: allow selecting property + unit in profile
        if (session.get('role') or '').lower() == 'tenant' and tenant_property_id_raw and tenant_unit_id_raw:
            try:
                tenant_property_id = int(tenant_property_id_raw)
                tenant_unit_id = int(tenant_unit_id_raw)
            except ValueError:
                flash('Invalid property/unit selection.', 'error')
                return redirect(url_for('auth.settings'))

            conn, cur, should_close = get_conn_and_cursor()
            try:
                # Validate unit belongs to property
                cur.execute(
                    """
                    SELECT id, unit_number, rent, status, tenant_id
                    FROM units
                    WHERE id = %s AND property_id = %s
                    """,
                    (tenant_unit_id, tenant_property_id),
                )
                unit = cur.fetchone()
                if not unit:
                    flash('Selected unit not found for that property.', 'error')
                    return redirect(url_for('auth.settings'))

                # Find or create a tenant profile linked to this user
                cur.execute("SELECT id, unit_id FROM tenants WHERE user_id = %s LIMIT 1", (user_id,))
                tenant = cur.fetchone()
                if not tenant:
                    cur.execute(
                        """
                        INSERT INTO tenants (name, phone, email, unit, amount, status,
                                             property_id, unit_id, user_id, created_at)
                        VALUES (%s, %s, %s, %s, %s, 'Active', %s, %s, %s, NOW())
                        """,
                        (
                            full_name or session.get('user_name') or 'Tenant',
                            phone or None,
                            email,
                            unit.get('unit_number'),
                            float(unit.get('rent') or 0),
                            tenant_property_id,
                            tenant_unit_id,
                            user_id,
                        ),
                    )
                    tenant_id = cur.lastrowid
                    previous_unit_id = None
                else:
                    tenant_id = tenant.get('id')
                    previous_unit_id = tenant.get('unit_id')

                # Prevent assigning into an already-occupied unit (unless it's already assigned to this tenant)
                occupied_by = unit.get('tenant_id')
                if occupied_by and int(occupied_by) != int(tenant_id):
                    flash('That unit is already assigned to another tenant.', 'error')
                    return redirect(url_for('auth.settings'))

                # Vacate previous unit (best-effort)
                if previous_unit_id and int(previous_unit_id) != int(tenant_unit_id):
                    cur.execute(
                        """
                        UPDATE units
                        SET tenant_id = NULL,
                            status = CASE WHEN status = 'Occupied' THEN 'Vacant' ELSE status END
                        WHERE id = %s AND tenant_id = %s
                        """,
                        (previous_unit_id, tenant_id),
                    )

                # Assign this unit to the tenant
                cur.execute(
                    """
                    UPDATE units
                    SET tenant_id = %s,
                        status = CASE WHEN status = 'Maintenance' THEN status ELSE 'Occupied' END
                    WHERE id = %s
                    """,
                    (tenant_id, tenant_unit_id),
                )
                cur.execute(
                    """
                    UPDATE tenants
                    SET property_id = %s,
                        unit_id = %s,
                        unit = %s,
                        amount = %s,
                        status = 'Active'
                    WHERE id = %s
                    """,
                    (
                        tenant_property_id,
                        tenant_unit_id,
                        unit.get('unit_number'),
                        float(unit.get('rent') or 0),
                        tenant_id,
                    ),
                )
                conn.commit()
                flash('Rental info updated.', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'Error saving rental info: {str(e)}', 'error')
            finally:
                cur.close()
                if should_close:
                    conn.close()

        return redirect(url_for('auth.settings'))

    properties_list = []
    tenant_profile = None
    tenant_units = []

    if (session.get('role') or '').lower() == 'tenant':
        conn, cur, should_close = get_conn_and_cursor()
        try:
            cur.execute("SELECT id, property_id, unit_id FROM tenants WHERE user_id = %s LIMIT 1", (session['user_id'],))
            tenant_profile = cur.fetchone()

            cur.execute("SELECT id, name, address FROM properties ORDER BY name")
            properties_list = [dict(r) for r in cur.fetchall()]

            if tenant_profile and tenant_profile.get('property_id'):
                cur.execute(
                    """
                    SELECT id, unit_number, status, tenant_id
                    FROM units
                    WHERE property_id = %s
                    ORDER BY unit_number
                    """,
                    (tenant_profile.get('property_id'),),
                )
                my_tid = tenant_profile.get('id')
                for r in cur.fetchall():
                    row = dict(r)
                    if row.get('tenant_id') and my_tid and int(row.get('tenant_id')) != int(my_tid):
                        continue
                    tenant_units.append({'id': row.get('id'), 'unit_number': row.get('unit_number'), 'status': row.get('status')})
        finally:
            cur.close()
            if should_close:
                conn.close()

    return render_template('settings.html', user=session, properties_list=properties_list, tenant_profile=tenant_profile, tenant_units=tenant_units)


# -------------------------
# CHANGE PASSWORD
# -------------------------
@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')

        if not all([current_pw, new_pw, confirm_pw]):
            flash('All fields are required', 'error')
            return redirect(url_for('auth.change_password'))

        if new_pw != confirm_pw:
            flash('New passwords do not match', 'error')
            return redirect(url_for('auth.change_password'))

        if len(new_pw) < 6:
            flash('Password must be at least 6 characters', 'error')
            return redirect(url_for('auth.change_password'))

        conn = mysql.connection if mysql.connection is not None else get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT password FROM users WHERE id = %s", (session['user_id'],))
        user = cur.fetchone()

        if not user or not check_password_hash(user['password'], current_pw):
            cur.close()
            flash('Current password is incorrect', 'error')
            return redirect(url_for('auth.change_password'))

        cur.execute(
            "UPDATE users SET password = %s WHERE id = %s",
            (generate_password_hash(new_pw), session['user_id'])
        )
        conn.commit()
        cur.close()

        flash('Password changed successfully', 'success')
        return redirect(url_for('auth.settings'))

    return render_template('change_password.html', user=session)


# -------------------------
# HELP
# -------------------------
@auth_bp.route('/help')
@login_required
def help():
    return render_template('help.html', user=session)
