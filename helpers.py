# helpers.py
import os
from decimal import Decimal
from functools import wraps
from flask import session, redirect, url_for, flash
import MySQLdb
from extensions import mysql, get_db_connection
from PIL import Image
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def get_cursor():
    """
    Legacy helper that returns (conn, cursor).

    Uses flask_mysqldb connection when available; otherwise falls back to a direct
    MySQLdb connection. Cursor is always DictCursor for consistent row access.
    """
    try:
        conn = mysql.connection
        if conn is not None:
            return conn, conn.cursor(MySQLdb.cursors.DictCursor)
    except Exception:
        pass

    conn = get_db_connection()
    return conn, conn.cursor(MySQLdb.cursors.DictCursor)


def allowed_file(filename):
    return filename and '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────
# IMAGE SAVING
# ─────────────────────────────────────────────
def save_property_image(image_file, property_id, upload_folder):
    """Save property image and return unique filename."""
    target_folder = os.path.join(upload_folder, 'properties')
    os.makedirs(target_folder, exist_ok=True)

    if not image_file or not image_file.filename:
        return None

    filename = secure_filename(image_file.filename)
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ['.jpg', '.jpeg', '.png', '.webp']:
        ext = '.jpg'

    timestamp = str(int(os.times()[4] * 1000))
    unique_name = f"prop_{property_id}_{timestamp}{ext}"
    filepath = os.path.join(target_folder, unique_name)

    try:
        image_file.seek(0)
        with Image.open(image_file) as img:
            img.thumbnail((800, 600), Image.Resampling.LANCZOS)
            if ext.lower() in ('.jpg', '.jpeg') and img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(filepath, 'JPEG', quality=85, optimize=True)
        print(f"✅ SAVED: {filepath}")
        return unique_name
    except Exception as e:
        print(f"❌ FAILED: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return None


# ─────────────────────────────────────────────
# SERIALIZATION
# ─────────────────────────────────────────────
def serialize_units(units):
    """Convert row-mappings to plain dicts, casting Decimal → float."""
    return [
        {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}
        for row in units
    ]


# ─────────────────────────────────────────────
# SYNC UNIT COUNT  (raw MySQL version)
# ─────────────────────────────────────────────
def sync_unit_count(property_id):
    """Recalculate and persist total_units for a property."""
    conn, cur = get_cursor()
    try:
        cur.execute("""
            UPDATE properties
            SET    total_units = (
                SELECT COUNT(*) FROM units WHERE property_id = %s
            )
            WHERE  id = %s
        """, (property_id, property_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"❌ sync_unit_count error: {e}")
    finally:
        cur.close()


# ─────────────────────────────────────────────
# LANDLORD STATS  (raw MySQL version)
# ─────────────────────────────────────────────
def get_landlord_stats(landlord_id):
    """Return aggregated property/unit stats for a landlord."""
    conn, cur = get_cursor()
    try:
        cur.execute("""
            SELECT
                COUNT(p.id)                     AS total_props,
                COALESCE(SUM(p.total_units), 0) AS total_units,
                COALESCE((
                    SELECT COUNT(*)
                    FROM   units u
                    JOIN   properties pp ON pp.id = u.property_id
                    WHERE  pp.landlord_id = %s AND u.status = 'Occupied'
                ), 0) AS occupied,
                COALESCE((
                    SELECT COUNT(*)
                    FROM   units u
                    JOIN   properties pp ON pp.id = u.property_id
                    WHERE  pp.landlord_id = %s AND u.status = 'Vacant'
                ), 0) AS vacant
            FROM properties p
            WHERE p.landlord_id = %s
        """, (landlord_id, landlord_id, landlord_id))
        row = cur.fetchone()
        return row or {
            'total_props': 0, 'total_units': 0,
            'occupied': 0,    'vacant': 0
        }
    except Exception as e:
        print(f"❌ get_landlord_stats error: {e}")
        return {'total_props': 0, 'total_units': 0, 'occupied': 0, 'vacant': 0}
    finally:
        cur.close()


# ─────────────────────────────────────────────
# GENERIC USER STATS
# ─────────────────────────────────────────────
def get_user_stats(user_id, role='landlord'):
    """Safe stats for any role."""
    if role == 'landlord':
        return get_landlord_stats(user_id)
    return {'total_bills': 0, 'pending_bills_count': 0, 'paid_bills': 0}


# ─────────────────────────────────────────────
# LOGIN REQUIRED DECORATOR
# ─────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated
