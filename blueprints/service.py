
from flask import Blueprint, render_template, redirect, session, url_for, flash
from helpers import login_required


service_bp = Blueprint('service', __name__)


# -------------------------
# SERVICE PROVIDER DASHBOARD
# -------------------------
@service_bp.route('/service-dashboard')
@login_required
def service_dashboard():
    if session.get('role') != 'service_provider':
        flash('Unauthorized access', 'error')
        return redirect(url_for('landing'))
    return render_template('service_dashboard.html', user=session)


@service_bp.route('/provider/jobs')
def jobs():
    return render_template('provider/jobs.html')

@service_bp.route('/provider/schedule')
def schedule():
    return render_template('provider/jobs.html')

@service_bp.route('/provider/jobs')
def reviews():
    return render_template('provider/jobs.html')


@service_bp.route('/provider/jobs')
def work_photos():
    return render_template('provider/jobs.html')

@service_bp.route('/provider/jobs')
def messages():
    return render_template('provider/jobs.html')
