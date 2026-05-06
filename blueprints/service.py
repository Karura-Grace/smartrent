import os
from datetime import date, timedelta

import MySQLdb
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from extensions import mysql, get_db_connection
from werkzeug.utils import secure_filename

from helpers import login_required


def service_provider_required(f):
    @login_required
    def decorated(*args, **kwargs):
        if session.get('role') != 'service_provider':
            flash('Unauthorized access', 'error')
            return redirect(url_for('landing'))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated


service_bp = Blueprint('service', __name__)

def _get_conn():
    return mysql.connection if mysql.connection is not None else get_db_connection()

def _get_cursor():
    conn = _get_conn()
    try:
        return conn, conn.cursor(MySQLdb.cursors.DictCursor), False
    except Exception:
        return conn, conn.cursor(), False

def _fetch_requests():
    conn = _get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute(
            """
            SELECT m.id, m.title, m.description, m.priority, m.status,
                   p.name AS property_name,
                   u.unit_number,
                   COALESCE(t.name, '-') AS tenant_name,
                   m.created_at, m.updated_at
            FROM maintenance_requests m
            LEFT JOIN properties p ON p.id = m.property_id
            LEFT JOIN units u      ON u.id = m.unit_id
            LEFT JOIN tenant t     ON t.id = m.tenant_id
            ORDER BY FIELD(m.priority,'High','Medium','Low'), m.created_at DESC
            """
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def _sample_jobs(provider_id):
    today = date.today()
    return [
        {
            'id': 1,
            'property_name': 'Sunset Apts',
            'unit': 'A-12',
            'description': 'Burst pipe',
            'priority': 'urgent',
            'status': 'in_progress',
            'scheduled_date': today,
        },
        {
            'id': 2,
            'property_name': 'Sunrise Apts',
            'unit': 'B-04',
            'description': 'No power socket',
            'priority': 'medium',
            'status': 'assigned',
            'scheduled_date': today + timedelta(days=1),
        },
        {
            'id': 3,
            'property_name': 'Cedar Court',
            'unit': 'C-07',
            'description': 'Clogged sink',
            'priority': 'low',
            'status': 'assigned',
            'scheduled_date': None,
        },
        {
            'id': 4,
            'property_name': 'Pine Residences',
            'unit': 'D-02',
            'description': 'Broken door lock',
            'priority': 'urgent',
            'status': 'completed',
            'scheduled_date': today - timedelta(days=2),
        },
        {
            'id': 5,
            'property_name': 'Maple Heights',
            'unit': 'E-11',
            'description': 'Leaking toilet',
            'priority': 'medium',
            'status': 'completed',
            'scheduled_date': today - timedelta(days=7),
        },
    ]


def _work_upload_dir():
    upload_root = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, 'static', 'uploads')
    work_dir = os.path.join(upload_root, 'work')
    os.makedirs(work_dir, exist_ok=True)
    return work_dir


def _list_work_photos(provider_id):
    work_dir = _work_upload_dir()
    prefix = f"sp_{provider_id}_"
    photos = []
    for name in sorted(os.listdir(work_dir), reverse=True):
        if not name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            continue
        if not name.startswith(prefix):
            continue
        photos.append({'image_path': name, 'caption': '', 'is_public': True})
    return photos


# -------------------------
# SERVICE PROVIDER DASHBOARD
# -------------------------
@service_bp.route('/service-dashboard')
@service_provider_required
def service_dashboard():
    provider_id = session.get('user_id')
    # Show real tenant requests as "jobs"
    jobs = _fetch_requests()
    open_count = sum(1 for j in jobs if (j.get('status') or '').lower() not in {'resolved', 'closed', 'completed', 'done'})
    unread_count = 2
    work_photos = _list_work_photos(provider_id)
    return render_template(
        'service_dashboard.html',
        user=session,
        jobs=jobs,
        open_count=open_count,
        unread_count=unread_count,
        work_photos=work_photos,
    )


@service_bp.route('/provider/requests')
@service_provider_required
def provider_requests():
    provider_id = session.get('user_id')
    jobs = _fetch_requests()
    open_count = sum(1 for j in jobs if (j.get('status') or '').lower() not in {'resolved', 'closed', 'completed', 'done'})
    unread_count = 0
    return render_template('provider/requests.html', user=session, jobs=jobs, open_count=open_count, unread_count=unread_count)


@service_bp.route('/provider/requests/<int:ticket_id>/seen', methods=['POST'])
@service_provider_required
def provider_mark_seen(ticket_id):
    conn = _get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("UPDATE maintenance_requests SET status='Seen', updated_at=NOW() WHERE id=%s", (ticket_id,))
        conn.commit()
        flash('Marked as seen.', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Error: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(request.referrer or url_for('service.provider_requests'))


@service_bp.route('/provider/requests/<int:ticket_id>/accept', methods=['POST'])
@service_provider_required
def provider_accept(ticket_id):
    conn = _get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cur.execute("UPDATE maintenance_requests SET status='In Progress', updated_at=NOW() WHERE id=%s", (ticket_id,))
        conn.commit()
        flash('Accepted (In Progress).', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Error: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(request.referrer or url_for('service.provider_requests'))


@service_bp.route('/provider/requests/<int:ticket_id>/done', methods=['POST'])
@service_provider_required
def provider_done(ticket_id):
    conn = _get_conn()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    try:
        # Mark ticket resolved
        cur.execute("UPDATE maintenance_requests SET status='Resolved', updated_at=NOW() WHERE id=%s", (ticket_id,))

        # Notify the tenant (best-effort via notices on the property)
        cur.execute(
            """
            SELECT m.id, m.title, m.property_id, p.landlord_id
            FROM maintenance_requests m
            LEFT JOIN properties p ON p.id = m.property_id
            WHERE m.id=%s
            """,
            (ticket_id,),
        )
        row = cur.fetchone() or {}
        if not isinstance(row, dict):
            row = dict(row)
        if row.get("property_id"):
            msg = f"Your service request #{ticket_id} ({row.get('title') or 'Request'}) has been marked as resolved."
            cur.execute(
                """
                INSERT INTO notices (landlord_id, sender_id, property_id, title, message, type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (row.get("landlord_id"), session.get("user_id"), row.get("property_id"), "Service Update", msg, "info"),
            )
        conn.commit()
        flash('Marked as resolved.', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Error: {str(e)}', 'error')
    finally:
        cur.close()
    return redirect(request.referrer or url_for('service.provider_requests'))


@service_bp.route('/provider/jobs')
@service_provider_required
def jobs():
    provider_id = session.get('user_id')
    jobs = _sample_jobs(provider_id)

    status = request.args.get('status')
    if status:
        if status == 'urgent':
            jobs = [j for j in jobs if j['priority'] == 'urgent' and j['status'] != 'completed']
        else:
            jobs = [j for j in jobs if j['status'] == status]

    open_count = len([j for j in _sample_jobs(provider_id) if j['status'] != 'completed'])
    unread_count = 2
    return render_template('provider/jobs.html', user=session, jobs=jobs, open_count=open_count, unread_count=unread_count)


@service_bp.route('/provider/jobs/completed')
@service_provider_required
def completed_jobs():
    provider_id = session.get('user_id')
    jobs = [j for j in _sample_jobs(provider_id) if j['status'] == 'completed']
    open_count = len([j for j in _sample_jobs(provider_id) if j['status'] != 'completed'])
    unread_count = 2
    return render_template('provider/jobs_completed.html', user=session, jobs=jobs, open_count=open_count, unread_count=unread_count)


@service_bp.route('/provider/jobs/<int:job_id>/complete', methods=['POST'])
@service_provider_required
def complete_job(job_id):
    flash(f'Job #{job_id} marked as completed (demo).', 'success')
    return redirect(request.referrer or url_for('service.jobs'))


@service_bp.route('/provider/jobs/<int:job_id>/photo', methods=['GET', 'POST'])
@service_provider_required
def job_photos(job_id):
    provider_id = session.get('user_id')

    if request.method == 'POST':
        photo = request.files.get('photo')
        if not photo or not photo.filename:
            flash('Please choose a photo to upload.', 'error')
            return redirect(url_for('service.job_photos', job_id=job_id))

        filename = secure_filename(photo.filename)
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            flash('Unsupported file type. Use PNG/JPG/WEBP.', 'error')
            return redirect(url_for('service.job_photos', job_id=job_id))

        target_name = f"sp_{provider_id}_job_{job_id}_{int(date.today().strftime('%Y%m%d'))}_{filename}"
        photo.save(os.path.join(_work_upload_dir(), target_name))
        flash('Photo uploaded successfully.', 'success')
        return redirect(url_for('service.job_photos', job_id=job_id))

    work_photos = _list_work_photos(provider_id)
    return render_template('provider/job_photos.html', user=session, job_id=job_id, work_photos=work_photos)


@service_bp.route('/provider/earnings')
@service_provider_required
def earnings():
    provider_id = session.get('user_id')
    jobs = _sample_jobs(provider_id)
    completed = [j for j in jobs if j['status'] == 'completed']
    total_jobs = len(completed)
    total_earned = 38500
    return render_template(
        'provider/earnings.html',
        user=session,
        total_jobs=total_jobs,
        total_earned=total_earned,
    )


@service_bp.route('/provider/schedule')
@service_provider_required
def schedule():
    provider_id = session.get('user_id')
    jobs = [j for j in _sample_jobs(provider_id) if j['status'] != 'completed']
    return render_template('provider/schedule.html', user=session, jobs=jobs)


@service_bp.route('/provider/reviews')
@service_provider_required
def reviews():
    demo_reviews = [
        {'tenant': 'Tenant', 'rating': 5, 'text': 'Arrived on time and fixed the issue quickly.', 'age': '5 days ago'},
        {'tenant': 'Tenant', 'rating': 4, 'text': 'Good work, communication could be faster.', 'age': '2 weeks ago'},
        {'tenant': 'Tenant', 'rating': 5, 'text': 'Very professional and clean finish.', 'age': '1 month ago'},
    ]
    return render_template('provider/reviews.html', user=session, reviews=demo_reviews)


@service_bp.route('/provider/photos')
@service_provider_required
def work_photos():
    provider_id = session.get('user_id')
    work_photos = _list_work_photos(provider_id)
    return render_template('provider/photos.html', user=session, work_photos=work_photos)


@service_bp.route('/provider/photos/upload', methods=['POST'])
@service_provider_required
def upload_work_photo():
    provider_id = session.get('user_id')
    photo = request.files.get('photo')
    if not photo or not photo.filename:
        flash('Please choose a photo to upload.', 'error')
        return redirect(url_for('service.work_photos'))

    filename = secure_filename(photo.filename)
    if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        flash('Unsupported file type. Use PNG/JPG/WEBP.', 'error')
        return redirect(url_for('service.work_photos'))

    target_name = f"sp_{provider_id}_{int(date.today().strftime('%Y%m%d'))}_{filename}"
    photo.save(os.path.join(_work_upload_dir(), target_name))
    flash('Photo uploaded successfully.', 'success')
    return redirect(url_for('service.work_photos'))


@service_bp.route('/providers/<int:provider_id>/portfolio')
def provider_portfolio(provider_id):
    work_photos = _list_work_photos(provider_id)
    return render_template('provider/portfolio.html', work_photos=work_photos, provider_id=provider_id)


@service_bp.route('/provider/messages')
@service_provider_required
def messages():
    provider_id = session.get('user_id')
    threads = [
        {'job_id': 1, 'title': 'Sunset Apts A-12 - Burst pipe', 'last': 'Can you share a photo after fix?', 'unread': 1},
        {'job_id': 2, 'title': 'Sunrise Apts B-04 - Power socket', 'last': 'Okay, I will come tomorrow.', 'unread': 0},
    ]
    unread_count = sum(t['unread'] for t in threads)
    return render_template('provider/messages.html', user=session, threads=threads, unread_count=unread_count)


@service_bp.route('/provider/messages/<int:job_id>', methods=['GET', 'POST'])
@service_provider_required
def message_thread(job_id):
    if request.method == 'POST':
        msg = (request.form.get('message') or '').strip()
        if msg:
            flash('Message sent (demo).', 'success')
        return redirect(url_for('service.message_thread', job_id=job_id))

    messages = [
        {'from': 'tenant', 'text': 'Hello, when can you come?', 'time': '09:10'},
        {'from': 'provider', 'text': 'I can be there tomorrow morning.', 'time': '09:12'},
    ]
    return render_template('provider/message_thread.html', user=session, job_id=job_id, messages=messages)
