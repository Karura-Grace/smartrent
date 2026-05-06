from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import mysql, get_db_connection, get_conn_and_cursor
from helpers import login_required
from tab_session import tab_session, get_tab_id, clear_tab_session

auth_bp = Blueprint('auth', __name__)


# -------------------------
# HELPERS
# -------------------------

ROLE_TABLE_MAP = {
    'tenant': 'tenant',
    'landlord': 'landlord',
    'agent': 'agent',
    'service_provider': 'service_provider',
}

def _table_has_column(cur, table, column):
    try:
        cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
        return bool(cur.fetchone())
    except Exception:
        return False

def _resolve_role_pk(cur, role, session_user_id):
    """
    Resolve the primary-key id for the role table.

    Most roles use `session['user_id']` as the role-table PK. Tenant may have
    historical sessions where it stores `users.id`, so we map to `tenant.id`.
    """
    if role == 'tenant':
        return resolve_tenant_id(cur, session_user_id) or session_user_id
    return session_user_id

def _sync_users_email(cur, role, role_table, role_pk, new_email, old_email=None):
    """
    Best-effort sync to `users.email`.

    - For role tables that have `user_id`, update by that FK.
    - For agent (often has no user_id), fall back to role+old_email match.
    """
    if role_table and _table_has_column(cur, role_table, "user_id"):
        cur.execute(f"SELECT user_id FROM `{role_table}` WHERE id=%s LIMIT 1", (role_pk,))
        row = cur.fetchone() or {}
        if not isinstance(row, dict):
            row = dict(row)
        user_id = row.get("user_id")
        if user_id:
            cur.execute("UPDATE users SET email=%s WHERE id=%s", (new_email, user_id))
            return

    if old_email:
        cur.execute(
            "UPDATE users SET email=%s WHERE LOWER(role)=%s AND LOWER(email)=%s",
            (new_email, role, (old_email or "").lower()),
        )

def resolve_tenant_id(cur, session_user_id):
    """
    Resolve the current tenant's primary key (`tenant.id`) from the session id.

    Supports both historical meanings of `session['user_id']`:
    - tenant.id
    - users.id (mapped via tenant.user_id)
    """
    if not session_user_id:
        return None

    cur.execute("SELECT id FROM tenant WHERE id=%s LIMIT 1", (session_user_id,))
    row = cur.fetchone()
    if row:
        return (dict(row) if not isinstance(row, dict) else row).get("id")

    cur.execute("SELECT id FROM tenant WHERE user_id=%s LIMIT 1", (session_user_id,))
    row = cur.fetchone()
    if row:
        return (dict(row) if not isinstance(row, dict) else row).get("id")

    return None

def get_user_by_email(email):
    """
    Search all role tables for a user with the given email.
    Returns (user_dict, role_name) or (None, None).
    """
    conn = mysql.connection if mysql.connection is not None else get_db_connection()
    cur = conn.cursor()
    for role, table in ROLE_TABLE_MAP.items():
        cur.execute(f"SELECT * FROM `{table}` WHERE email = %s LIMIT 1", (email,))
        row = cur.fetchone()
        if row:
            cur.close()
            return dict(row), role
    cur.close()
    return None, None


# -------------------------
# LOGIN
# -------------------------
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            flash('All fields are required', 'error')
            return redirect(url_for('auth.login'))

        user, role = get_user_by_email(email)

        if not user:
            flash('Invalid email', 'error')
            return redirect(url_for('auth.login'))

        if not check_password_hash(user['password'], password):
            flash('Wrong password', 'error')
            return redirect(url_for('auth.login'))

        # Populate tab session
        ts = tab_session()
        ts['user_id']    = user['id']
        ts['user_email'] = user['email']
        ts['role']       = role
        first = user.get('first_name', '')
        last  = user.get('last_name', '')
        ts['user_name']  = f"{first} {last}".strip()
        session.modified = True

        flash(f"Welcome {first}!", 'success')
        tab_id = get_tab_id()

        def _r(endpoint):
            return redirect(url_for(endpoint, tab_id=tab_id) if tab_id else url_for(endpoint))

        if role == 'tenant':
            return _r('tenant.tenant_dashboard')
        elif role == 'landlord':
            return _r('landlord.landlord_dashboard')
        elif role == 'service_provider':
            return _r('service.service_dashboard')
        elif role == 'agent':
            return _r('agent.agent_dashboard')

    return render_template('login.html')


# -------------------------
# REGISTER
# -------------------------
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name  = request.form.get('last_name', '').strip()
        email      = request.form.get('email', '').strip()
        password   = request.form.get('password', '')
        confirm    = request.form.get('confirm_password', '')
        role       = request.form.get('role', '').strip()

        # Validating the user 
        if not all([first_name, last_name, email, password, confirm, role]):
            flash('All fields are required', 'error')
            return redirect(url_for('auth.register'))

        if role not in ROLE_TABLE_MAP:
            flash('Invalid role selected', 'error')
            return redirect(url_for('auth.register'))

        if password != confirm:
            flash('Passwords do not match', 'error')
            return redirect(url_for('auth.register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return redirect(url_for('auth.register'))

        #  Check email uniqueness across ALL role tables
        existing_user, _ = get_user_by_email(email)
        if existing_user:
            flash('Email already registered', 'error')
            return redirect(url_for('auth.register'))

        hashed_password = generate_password_hash(password)

        conn = mysql.connection if mysql.connection is not None else get_db_connection()
        cur  = conn.cursor()

        try:
            #  inserting  a record in users table for FK references 
            cur.execute(
                "INSERT INTO users (email, role ) VALUES (%s, %s)",
                (email, role)
            )
            user_id = cur.lastrowid

            # Insert into role-specific table 
            if role == 'tenant':
                cur.execute(
                    """
                    INSERT INTO tenant
                        (user_id, first_name, last_name, email, password, role, name, status)
                    VALUES (%s, %s, %s, %s, %s, 'tenant', %s, 'Active')
                    """,
                    (user_id, first_name, last_name, email, hashed_password,
                     f"{first_name} {last_name}")
                )

            elif role == 'landlord':
                cur.execute(
                    """
                    INSERT INTO landlord
                        (user_id, first_name, last_name, email, password, role)
                    VALUES (%s, %s, %s, %s, %s, 'landlord')
                    """,
                    (user_id, first_name, last_name, email, hashed_password)
                )

            elif role == 'agent':
                cur.execute(
                    """
                    INSERT INTO agent
                        (landlord_id, first_name, last_name, email, password, role, property_id)
                    VALUES (0, %s, %s, %s, %s, 'agent', 0)
                    """,
                    (first_name, last_name, email, hashed_password)
                )

            elif role == 'service_provider':
                cur.execute(
                    """
                    INSERT INTO service_provider
                        (user_id, first_name, last_name, email, password, status)
                    VALUES (%s, %s, %s, %s, %s, 'Active')
                    """,
                    (user_id, first_name, last_name, email, hashed_password)
                )

            conn.commit()
            flash('Registered successfully. Please login.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            conn.rollback()
            flash(f'Registration failed: {str(e)}', 'error')
            return redirect(url_for('auth.register'))
        finally:
            cur.close()

    return render_template('register.html')


# -------------------------
# LOGOUT
# -------------------------
@auth_bp.route('/logout')
def logout():
    clear_tab_session()
    flash('Logged out successfully', 'success')
    tab_id = get_tab_id()
    return redirect(url_for('auth.login', tab_id=tab_id) if tab_id else url_for('auth.login'))


# -------------------------
# SETTINGS
# -------------------------
@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        user_id   = session.get('user_id')
        role      = (session.get('role') or '').lower()
        full_name = request.form.get('full_name', '').strip()
        email     = request.form.get('email', '').strip()
        phone     = request.form.get('phone', '').strip()
        if not full_name or not email:
            flash('Name and email are required', 'error')
            return redirect(url_for('auth.settings'))

        parts      = [p for p in full_name.split(' ') if p]
        first_name = parts[0] if parts else full_name
        last_name  = ' '.join(parts[1:]) if len(parts) > 1 else ''

        table = ROLE_TABLE_MAP.get(role)

        if table:
            conn, cur, should_close = get_conn_and_cursor()
            try:
                role_pk  = _resolve_role_pk(cur, role, user_id)
                old_email = session.get('user_email') or ''
                if role == 'service_provider':
                    cur.execute(
                        """
                        UPDATE service_provider
                        SET first_name=%s, last_name=%s, email=%s, phone=%s
                        WHERE id=%s
                        """,
                        (first_name, last_name, email, phone or None, role_pk)
                    )
                elif role == 'tenant':
                    cur.execute(
                        """
                        UPDATE tenant
                        SET first_name=%s, last_name=%s, name=%s, email=%s, phone=%s
                        WHERE id=%s
                        """,
                        (first_name, last_name, full_name, email, phone or None, role_pk)
                    )
                elif role == 'landlord':
                    if _table_has_column(cur, "landlord", "phone"):
                        cur.execute(
                            """
                            UPDATE landlord
                            SET first_name=%s, last_name=%s, email=%s, phone=%s
                            WHERE id=%s
                            """,
                            (first_name, last_name, email, phone or None, role_pk),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE landlord
                            SET first_name=%s, last_name=%s, email=%s
                            WHERE id=%s
                            """,
                            (first_name, last_name, email, role_pk),
                        )
                elif role == 'agent':
                    cur.execute(
                        """
                        UPDATE agent
                        SET first_name=%s, last_name=%s, email=%s
                        WHERE id=%s
                        """,
                        (first_name, last_name, email, role_pk)
                    )

                # Also keep users table email in sync
                _sync_users_email(cur, role, table, role_pk, email, old_email=old_email)

                conn.commit()
                ts = tab_session()
                ts['user_name']  = full_name
                ts['user_email'] = email
                session.modified = True
                flash('Settings saved successfully', 'success')

            except Exception as e:
                conn.rollback()
                flash(f'Error saving settings: {str(e)}', 'error')
            finally:
                cur.close()
                if should_close:
                    conn.close()

        # -- Tenant unit/property assignment ---------------------
        if role == 'tenant':
            tenant_property_id_raw = (request.form.get('tenant_property_id') or '').strip()
            tenant_unit_id_raw     = (request.form.get('tenant_unit_id') or '').strip()

            if tenant_property_id_raw and tenant_unit_id_raw:
                try:
                    tenant_property_id = int(tenant_property_id_raw)
                    tenant_unit_id     = int(tenant_unit_id_raw)
                except ValueError:
                    flash('Invalid property/unit selection', 'error')
                    return redirect(url_for('auth.settings'))

                conn, cur, should_close = get_conn_and_cursor()
                try:
                    # Validate unit belongs to property
                    cur.execute(
                        """
                        SELECT id, unit_number, rent, status, tenant_id
                        FROM units
                        WHERE id=%s AND property_id=%s
                        """,
                        (tenant_unit_id, tenant_property_id)
                    )
                    unit = cur.fetchone()
                    if not unit:
                        flash('Selected unit not found for that property', 'error')
                        return redirect(url_for('auth.settings'))

                    unit = dict(unit)

                    tenant_id = resolve_tenant_id(cur, user_id)
                    if not tenant_id:
                        flash('Tenant profile not found', 'error')
                        return redirect(url_for('auth.settings'))

                    # Get current tenant row (by tenant_id)
                    cur.execute("SELECT id, unit_id FROM tenant WHERE id=%s LIMIT 1", (tenant_id,))
                    tenant_row = cur.fetchone()
                    if not tenant_row:
                        flash('Tenant profile not found', 'error')
                        return redirect(url_for('auth.settings'))

                    tenant_row     = dict(tenant_row)
                    previous_unit  = tenant_row.get('unit_id')

                    # Check unit not occupied by someone else
                    occupied_by = unit.get('tenant_id')
                    if occupied_by and int(occupied_by) != int(tenant_id):
                        flash('That unit is already assigned to another tenant', 'error')
                        return redirect(url_for('auth.settings'))

                    # Vacate previous unit
                    if previous_unit and int(previous_unit) != int(tenant_unit_id):
                        cur.execute(
                            """
                            UPDATE units
                            SET tenant_id=NULL, status='Vacant'
                            WHERE id=%s AND tenant_id=%s
                            """,
                            (previous_unit, tenant_id)
                        )

                    # Assign new unit
                    cur.execute(
                        "UPDATE units SET tenant_id=%s, status='Occupied' WHERE id=%s",
                        (tenant_id, tenant_unit_id)
                    )

                    # Update tenant row
                    cur.execute(
                        """
                        UPDATE tenant
                        SET property_id=%s, unit_id=%s, amount=%s, status='Active'
                        WHERE id=%s
                        """,
                        (tenant_property_id, tenant_unit_id,
                         float(unit.get('rent') or 0), tenant_id)
                    )

                    conn.commit()
                    flash('Rental info updated', 'success')

                except Exception as e:
                    conn.rollback()
                    flash(f'Error saving rental info: {str(e)}', 'error')
                finally:
                    cur.close()
                    if should_close:
                        conn.close()

        return redirect(url_for('auth.settings'))

    # -- GET: load current profile --------------------------------
    role           = (session.get('role') or '').lower()
    user_id        = session.get('user_id')
    properties_list = []
    tenant_profile  = None
    tenant_units    = []
    current_user    = {}

    table = ROLE_TABLE_MAP.get(role)
    if table:
        conn, cur, should_close = get_conn_and_cursor()
        try:
            cur.execute(f"SELECT * FROM `{table}` WHERE id=%s LIMIT 1", (user_id,))
            row = cur.fetchone()
            if row:
                current_user = dict(row)
        finally:
            cur.close()
            if should_close:
                conn.close()

    if role == 'tenant':
        conn, cur, should_close = get_conn_and_cursor()
        try:
            tenant_id = resolve_tenant_id(cur, user_id)
            if tenant_id:
                cur.execute(
                    "SELECT id, property_id, unit_id FROM tenant WHERE id=%s LIMIT 1",
                    (tenant_id,)
                )
            else:
                cur.execute(
                    "SELECT id, property_id, unit_id FROM tenant WHERE id=%s LIMIT 1",
                    (user_id,)
                )
            row = cur.fetchone()
            tenant_profile = dict(row) if row else None

            cur.execute("SELECT id, name, address FROM properties ORDER BY name")
            properties_list = [dict(r) for r in cur.fetchall()]

            if tenant_profile and tenant_profile.get('property_id'):
                cur.execute(
                    """
                    SELECT id, unit_number, status, tenant_id
                    FROM units
                    WHERE property_id=%s
                    ORDER BY unit_number
                    """,
                    (tenant_profile['property_id'],)
                )
                my_tid = tenant_profile.get('id')
                for r in cur.fetchall():
                    r = dict(r)
                    if r.get('tenant_id') and my_tid and int(r['tenant_id']) != int(my_tid):
                        continue
                    tenant_units.append({
                        'id':          r['id'],
                        'unit_number': r['unit_number'],
                        'status':      r['status']
                    })
        finally:
            cur.close()
            if should_close:
                conn.close()

    return render_template(
        'settings.html',
        user=session,
        current_user=current_user,
        properties_list=properties_list,
        tenant_profile=tenant_profile,
        tenant_units=tenant_units
    )


# -------------------------
# CHANGE PASSWORD
# -------------------------
@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw     = request.form.get('new_password', '')
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

        role  = (session.get('role') or '').lower()
        table = ROLE_TABLE_MAP.get(role)

        if not table:
            flash('Unknown role', 'error')
            return redirect(url_for('auth.change_password'))

        conn, cur, should_close = get_conn_and_cursor()
        try:
            role_pk = _resolve_role_pk(cur, role, session.get('user_id'))
            cur.execute(f"SELECT password FROM `{table}` WHERE id=%s LIMIT 1", (role_pk,))
            row = cur.fetchone()
            if row and not isinstance(row, dict):
                row = dict(row)

            if not row or not check_password_hash((row.get('password') or ''), current_pw):
                flash('Current password is incorrect', 'error')
                return redirect(url_for('auth.change_password'))

            cur.execute(
                f"UPDATE `{table}` SET password=%s WHERE id=%s",
                (generate_password_hash(new_pw), role_pk)
            )
            conn.commit()
        finally:
            cur.close()
            if should_close:
                conn.close()

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
