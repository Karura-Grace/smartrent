# blueprints/properties.py - FULL WORKING CODE
import os
from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify, current_app
from extensions import mysql
from helpers import login_required, get_user_stats, save_property_image, get_landlord_stats

properties_bp = Blueprint('properties', __name__)  # ✅ properties (not properties_bp)

@properties_bp.route('/properties')
@login_required
def properties():  # ✅ Simple name
    landlord_id = session['user_id']
    cur = mysql.connection.cursor()
    
    cur.execute("""
        SELECT p.*, 
               COALESCE(u_count.unit_count, 0) AS unit_count,
               COALESCE(u_occupied.occupied_count, 0) AS occupied_count,
               COALESCE(u_vacant.vacant_count, 0) AS vacant_count
        FROM properties p
        LEFT JOIN (
            SELECT property_id, COUNT(*) as unit_count 
            FROM units GROUP BY property_id
        ) u_count ON u_count.property_id = p.id
        LEFT JOIN (
            SELECT property_id, COUNT(*) as occupied_count 
            FROM units WHERE status = 'Occupied' GROUP BY property_id
        ) u_occupied ON u_occupied.property_id = p.id
        LEFT JOIN (
            SELECT property_id, COUNT(*) as vacant_count 
            FROM units WHERE status = 'Vacant' GROUP BY property_id
        ) u_vacant ON u_vacant.property_id = p.id
        WHERE p.landlord_id = %s
        ORDER BY p.created_at DESC
    """, (landlord_id,))
    
    properties_list = []
    for row in cur.fetchall():
        prop_dict = dict(row)
        prop_dict['image'] = prop_dict.get('image', '')  # ✅ Fix for template
        properties_list.append(prop_dict)
    
    cur.close()
    stats = get_user_stats(landlord_id)
    return render_template('properties.html', user=session, properties=properties_list, stats=stats)

@properties_bp.route('/properties/add', methods=['POST'])
@login_required
def add():
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip()
    city = request.form.get('city', 'Nairobi').strip()
    prop_type = request.form.get('type', 'Apartments')
    description = request.form.get('description', '').strip()

    try:
        total_units = int(request.form.get('total_units') or 0)
        base_rent = float(request.form.get('base_rent') or 0)
    except:
        total_units, base_rent = 0, 0.0

    if not name or not address:
        flash('Name and address are required.', 'error')
        return redirect(url_for('properties.properties'))

    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (landlord_id, name, address, city, type, total_units, base_rent, description, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Active', NOW())
        """, (session['user_id'], name, address, city, prop_type, total_units, base_rent, description))
        mysql.connection.commit()
        new_id = cur.lastrowid

        # Handle image using YOUR helper function
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            filename = save_property_image(image_file, new_id, upload_folder)
            if filename:
                cur.execute("UPDATE properties SET image = %s WHERE id = %s", (filename, new_id))
                mysql.connection.commit()

        flash(f'"{name}" created successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error creating property: {str(e)}', 'error')
    finally:
        cur.close()
    
    return redirect(url_for('properties.properties'))

@properties_bp.route('/properties/edit/<int:property_id>', methods=['POST'])
@login_required
def edit(property_id):
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip()
    city = request.form.get('city', '').strip()
    prop_type = request.form.get('type', '')
    status = request.form.get('status', 'Active')
    description = request.form.get('description', '').strip()
    
    try:
        total_units = int(request.form.get('total_units') or 0)
        base_rent = float(request.form.get('base_rent') or 0)
    except:
        total_units, base_rent = 0, 0.0

    cur = mysql.connection.cursor()
    try:
        cur.execute("SELECT image FROM properties WHERE id = %s AND landlord_id = %s", 
                   (property_id, session['user_id']))
        prop = cur.fetchone()
        
        if not prop:
            flash('Property not found.', 'error')
            return redirect(url_for('properties.properties'))

        # Handle new image
        image_file = request.files.get('image')
        new_filename = None
        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
        
        if image_file and image_file.filename:
            old_filename = prop['image']
            new_filename = save_property_image(image_file, property_id, upload_folder)
            if new_filename and old_filename:
                old_path = os.path.join(upload_folder, old_filename)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except:
                        pass

        if new_filename:
            cur.execute("""
                UPDATE properties SET name=%s, address=%s, city=%s, `type`=%s, total_units=%s, 
                    base_rent=%s, description=%s, status=%s, image=%s 
                WHERE id=%s AND landlord_id=%s
            """, (name, address, city, prop_type, total_units, base_rent, 
                  description, status, new_filename, property_id, session['user_id']))
        else:
            cur.execute("""
                UPDATE properties SET name=%s, address=%s, city=%s, `type`=%s, total_units=%s, 
                    base_rent=%s, description=%s, status=%s 
                WHERE id=%s AND landlord_id=%s
            """, (name, address, city, prop_type, total_units, base_rent, 
                  description, status, property_id, session['user_id']))
        
        mysql.connection.commit()
        flash('Property updated successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error updating property: {str(e)}', 'error')
    finally:
        cur.close()
    
    return redirect(url_for('properties.properties'))

@properties_bp.route('/properties/delete/<int:property_id>', methods=['POST'])
@login_required
def delete(property_id):
    cur = mysql.connection.cursor()
    try:
        cur.execute("SELECT image FROM properties WHERE id = %s AND landlord_id = %s", 
                   (property_id, session['user_id']))
        prop = cur.fetchone()
        
        cur.execute("DELETE FROM properties WHERE id = %s AND landlord_id = %s", 
                   (property_id, session['user_id']))
        mysql.connection.commit()
        
        # Delete image file
        if prop and prop['image']:
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            image_path = os.path.join(upload_folder, prop['image'])
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except:
                    pass
        
        flash('Property deleted successfully.', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error deleting property: {str(e)}', 'error')
    finally:
        cur.close()
    
    return redirect(url_for('properties.properties'))

@properties_bp.route('/properties/<int:property_id>/units')
@login_required
def get_units(property_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT u.id, u.unit_number, u.floor, u.type, u.rent, u.status,
               COALESCE(CONCAT(t.first_name, ' ', t.last_name), '—') as tenant_name
        FROM units u
        LEFT JOIN tenants t ON u.tenant_id = t.id
        WHERE u.property_id = %s
        ORDER BY u.unit_number
    """, (property_id,))
    units = []
    for row in cur.fetchall():
        unit_dict = dict(row)
        unit_dict['rent'] = float(unit_dict.get('rent', 0))
        units.append(unit_dict)
    cur.close()
    return jsonify({'units': units})