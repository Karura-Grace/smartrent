# helpers.py
import os
import time
from decimal import Decimal
from functools import wraps
from tkinter import Image
from flask import session, redirect, url_for, flash
from extensions import mysql
import uuid
from PIL import Image
from werkzeug.utils import secure_filename
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return filename and '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_property_image(image_file, property_id, upload_folder):
    """Save property image - FIXED for Windows"""
    
    # ✅ CORRECT PATH - NO NESTING
    target_folder = os.path.join(upload_folder, 'properties')  # static/uploads/properties
    os.makedirs(target_folder, exist_ok=True)
    
    if not image_file or not image_file.filename:
        return None
    
    # Secure filename
    filename = secure_filename(image_file.filename)
    name, ext = os.path.splitext(filename)
    if not ext.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
        ext = '.jpg'
    
    # Unique name: prop_16_1775843900.jpg
    timestamp = str(int(os.times()[4] * 1000))
    unique_name = f"prop_{property_id}_{timestamp}{ext}"
    filepath = os.path.join(target_folder, unique_name)
    
    try:
        image_file.seek(0)  # Reset file pointer
        with Image.open(image_file) as img:
            img.thumbnail((800, 600), Image.Resampling.LANCZOS)
            if ext == '.jpg' and img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(filepath, 'JPEG', quality=85, optimize=True)
        
        print(f"✅ SAVED: {filepath}")  # Debug
        return unique_name  # Just filename: "prop_16_1775843900.jpg"
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return None

def serialize_units(units):
    return [{k: float(v) if isinstance(v, Decimal) else v
             for k, v in row.items()} for row in units]

def sync_unit_count(cur, property_id):
    cur.execute(
        "UPDATE properties SET total_units = "
        "(SELECT COUNT(*) FROM units WHERE property_id = %s) WHERE id = %s",
        (property_id, property_id)
    )

def get_landlord_stats(landlord_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT COUNT(p.id) AS total_props,
               COALESCE(SUM(p.total_units), 0) AS total_units,
               COALESCE((SELECT COUNT(*) FROM units u JOIN properties pp ON pp.id = u.property_id
                         WHERE pp.landlord_id = %s AND u.status = 'Occupied'), 0) AS occupied,
               COALESCE((SELECT COUNT(*) FROM units u JOIN properties pp ON pp.id = u.property_id
                         WHERE pp.landlord_id = %s AND u.status = 'Vacant'), 0) AS vacant
        FROM properties p WHERE p.landlord_id = %s
    """, (landlord_id, landlord_id, landlord_id))
    stats = cur.fetchone()
    cur.close()
    return stats

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

def get_user_stats(user_id, role='landlord'):
    """Safe stats for any role"""
    if role == 'landlord':
        return get_landlord_stats(user_id)  # Use your existing function
    else:
        # Default for tenants
        return {'total_bills': 0, 'pending_bills_count': 0, 'paid_bills': 0}