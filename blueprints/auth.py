from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import mysql
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

        cur = mysql.connection.cursor()
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

        cur = mysql.connection.cursor()
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
        mysql.connection.commit()
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

        if full_name and email:
            cur = mysql.connection.cursor()
            cur.execute(
                "UPDATE users SET name=%s, email=%s WHERE id=%s",
                (full_name, email, user_id)
            )
            mysql.connection.commit()
            cur.close()

            # Update session so topbar name refreshes
            session['user_name'] = full_name
            session['user_email'] = email

            flash('Settings saved successfully', 'success')
        else:
            flash('Name and email are required', 'error')

        return redirect(url_for('auth.settings'))

    return render_template('settings.html', user=session)


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

        cur = mysql.connection.cursor()
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
        mysql.connection.commit()
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