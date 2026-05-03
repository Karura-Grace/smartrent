import os
from datetime import date, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
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
    jobs = _sample_jobs(provider_id)
    open_count = len([j for j in jobs if j['status'] != 'completed'])
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
        {'job_id': 1, 'title': 'Sunset Apts A-12 · Burst pipe', 'last': 'Can you share a photo after fix?', 'unread': 1},
        {'job_id': 2, 'title': 'Sunrise Apts B-04 · Power socket', 'last': 'Okay, I will come tomorrow.', 'unread': 0},
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
