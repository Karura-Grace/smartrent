from flask import Blueprint, render_template, redirect, session, url_for, flash
from helpers import login_required

tenant_bp = Blueprint('tenant', __name__)


# -------------------------
# TENANT DASHBOARD
# -------------------------
@tenant_bp.route('/tenant-dashboard')
@login_required
def tenant_dashboard():
    if session.get('role') != 'tenant':
        flash('Unauthorized access', 'error')
        return redirect(url_for('landing'))
    return render_template('tenantdashboard.html', user=session)





# -------------------------
# PAYMENTS
# -------------------------
@tenant_bp.route('/payments')
@login_required
def payments():
    if session.get('role') != 'tenant':
        flash('Unauthorized access', 'error')
        return redirect(url_for('landing'))
    return render_template('payments.html', user=session)


# -------------------------
# BILLS
# -------------------------
@tenant_bp.route('/bills')
@login_required
def bills():
    if session.get('role') != 'tenant':
        flash('Unauthorized access', 'error')
        return redirect(url_for('landing'))
    return render_template('bills.html', user=session)


# -------------------------
# SERVICES
# -------------------------
@tenant_bp.route('/services')
@login_required
def services():
    if session.get('role') != 'tenant':
        flash('Unauthorized access', 'error')
        return redirect(url_for('landing'))
    return render_template('services.html', user=session)