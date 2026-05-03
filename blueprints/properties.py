# blueprints/properties.py - FULL WORKING CODE
import os
import MySQLdb
from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify, current_app
from extensions import mysql, get_db_connection
from helpers import login_required, get_user_stats, save_property_image

properties_bp = Blueprint('properties', __name__)  # ✅ properties (not properties_bp)

def get_conn_and_cursor():
    """
    Returns (conn, cur, should_close_conn).

    Ensures commit()/rollback() is called on the same connection that created the cursor.
    """
    try:
        if mysql.connection is not None:
            conn = mysql.connection
            cur = conn.cursor(MySQLdb.cursors.DictCursor)
            return conn, cur, False
    except Exception:
        pass

    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    return conn, cur, True

@properties_bp.route('/properties')
@login_required
def properties():  # ✅ Simple name
    landlord_id = session['user_id']
    conn, cur, should_close = get_conn_and_cursor()
    
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
    if should_close:
        conn.close()
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

    conn, cur, should_close = get_conn_and_cursor()
    try:
        cur.execute("""
            INSERT INTO properties (landlord_id, name, address, city, type, total_units, base_rent, description, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Active', NOW())
        """, (session['user_id'], name, address, city, prop_type, total_units, base_rent, description))
        conn.commit()
        new_id = cur.lastrowid

        # Handle image using YOUR helper function
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            filename = save_property_image(image_file, new_id, upload_folder)
            if filename:
                cur.execute("UPDATE properties SET image = %s WHERE id = %s", (filename, new_id))
                conn.commit()

        flash(f'"{name}" created successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error creating property: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()
    
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

    conn, cur, should_close = get_conn_and_cursor()
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
            old_filename = (prop or {}).get('image')
            new_filename = save_property_image(image_file, property_id, upload_folder)
            if new_filename and old_filename:
                old_path = os.path.join(upload_folder, 'properties', old_filename)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
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
        
        conn.commit()
        flash('Property updated successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating property: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()
    
    return redirect(url_for('properties.properties'))

@properties_bp.route('/properties/delete/<int:property_id>', methods=['POST'])
@login_required
def delete(property_id):
    conn, cur, should_close = get_conn_and_cursor()
    try:
        cur.execute("SELECT image FROM properties WHERE id = %s AND landlord_id = %s", 
                   (property_id, session['user_id']))
        prop = cur.fetchone()
        
        cur.execute("DELETE FROM properties WHERE id = %s AND landlord_id = %s", 
                   (property_id, session['user_id']))
        conn.commit()
        
        # Delete image file
        if prop and prop.get('image'):
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            image_path = os.path.join(upload_folder, 'properties', prop['image'])
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception:
                    pass
        
        flash('Property deleted successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting property: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()
    
    return redirect(url_for('properties.properties'))

def _get_units_json_for_landlord(landlord_id, property_id):
    conn, cur, should_close = get_conn_and_cursor()
    try:
        cur.execute("SELECT id FROM properties WHERE id = %s AND landlord_id = %s", (property_id, landlord_id))
        if not cur.fetchone():
            return None, conn, cur, should_close

        cur.execute("""
            SELECT u.id, u.unit_number, u.floor, u.type, u.rent, u.status,
                   COALESCE(t.name, '—') AS tenant_name
            FROM units u
            LEFT JOIN tenants t ON t.id = u.tenant_id
            WHERE u.property_id = %s
            ORDER BY u.unit_number
        """, (property_id,))

        units = []
        for row in cur.fetchall():
            unit_dict = dict(row)
            unit_dict['rent'] = float(unit_dict.get('rent', 0) or 0)
            units.append(unit_dict)
        return jsonify({'units': units}), conn, cur, should_close
    except Exception:
        return jsonify({'units': []}), conn, cur, should_close


@properties_bp.route('/properties/<int:property_id>/units')
@login_required
def get_units(property_id):
    landlord_id = session['user_id']
    resp, conn, cur, should_close = _get_units_json_for_landlord(landlord_id, property_id)
    try:
        if resp is None:
            return jsonify({'error': 'Not found'}), 404
        return resp
    finally:
        try:
            cur.close()
        finally:
            if should_close:
                conn.close()

@properties_bp.route('/properties/<int:property_id>/units-raw')
@login_required
def get_units_raw(property_id):
    return get_units(property_id)

    # Legacy implementation (unreachable)
    cur = get_cursor()
    cur.execute("""
        SELECT u.id, u.unit_number, u.floor, u.type, u.rent, u.status,
               COALESCE(t.name, '—') as tenant_name
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
# ─────────────────────────────────────────────────────────────
# ADD THIS ROUTE to blueprints/properties.py
# Place it alongside the other @properties_bp.route definitions
# ─────────────────────────────────────────────────────────────

@properties_bp.route('/units')
@login_required
def units_page():
    """Standalone units management page — shows all properties + their units."""
    landlord_id = session['user_id']
    conn, cur, should_close = get_conn_and_cursor()

    cur.execute("""
        SELECT p.*,
               COALESCE(u_count.unit_count, 0)     AS unit_count,
               COALESCE(u_occupied.occupied_count, 0) AS occupied_count,
               COALESCE(u_vacant.vacant_count, 0)   AS vacant_count
        FROM properties p
        LEFT JOIN (
            SELECT property_id, COUNT(*) as unit_count
            FROM units GROUP BY property_id
        ) u_count     ON u_count.property_id = p.id
        LEFT JOIN (
            SELECT property_id, COUNT(*) as occupied_count
            FROM units WHERE status = 'Occupied' GROUP BY property_id
        ) u_occupied  ON u_occupied.property_id = p.id
        LEFT JOIN (
            SELECT property_id, COUNT(*) as vacant_count
            FROM units WHERE status = 'Vacant' GROUP BY property_id
        ) u_vacant    ON u_vacant.property_id = p.id
        WHERE p.landlord_id = %s
        ORDER BY p.created_at DESC
    """, (landlord_id,))

    properties_list = [dict(row) for row in cur.fetchall()]

    # Tenants dropdown (used by units.html edit/add modals)
    cur.execute("""
        SELECT t.id, t.name, t.unit, t.phone
        FROM tenants t
        JOIN properties p ON p.id = t.property_id
        WHERE p.landlord_id = %s
        ORDER BY t.name
    """, (landlord_id,))
    tenants = [dict(r) for r in cur.fetchall()]

    cur.close()
    if should_close:
        conn.close()

    stats = get_user_stats(landlord_id)
    return render_template('units.html', user=session, properties=properties_list, tenants=tenants, stats=stats)


# ─────────────────────────────────────────────────────────────
# ADD THIS ROUTE for editing units (POST handler)
# Also add a matching route in agent blueprint if needed
# ─────────────────────────────────────────────────────────────

@properties_bp.route('/units/edit/<int:unit_id>', methods=['POST'])
@login_required
def edit_unit(unit_id):
    unit_number = request.form.get('unit_number', '').strip()
    floor       = request.form.get('floor') or None
    unit_type   = request.form.get('type', '')
    status      = request.form.get('status', 'Vacant')
    rent        = request.form.get('rent') or 0
    tenant_id_raw = (request.form.get('tenant_id') or '').strip()

    try:
        floor = int(floor) if floor else None
        rent  = float(rent)
    except (ValueError, TypeError):
        floor, rent = None, 0.0
    
    try:
        tenant_id = int(tenant_id_raw) if tenant_id_raw else None
    except ValueError:
        tenant_id = None

    conn, cur, should_close = get_conn_and_cursor()
    try:
        # Verify unit belongs to this landlord
        cur.execute("""
            SELECT u.id, u.property_id, u.tenant_id
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE u.id = %s AND p.landlord_id = %s
        """, (unit_id, session['user_id']))

        unit_row = cur.fetchone()
        if not unit_row:
            flash('Unit not found.', 'error')
            return redirect(url_for('properties.html'))

        property_id = unit_row.get('property_id')
        previous_tenant_id = unit_row.get('tenant_id')

        # If tenant assignment changed, keep tenants/units in sync (best-effort)
        if previous_tenant_id and previous_tenant_id != tenant_id:
            cur.execute(
                "UPDATE tenants SET unit_id = NULL WHERE id = %s AND unit_id = %s",
                (previous_tenant_id, unit_id),
            )

        if tenant_id:
            # Validate tenant exists
            cur.execute("SELECT id FROM tenants WHERE id = %s", (tenant_id,))
            if not cur.fetchone():
                flash('Selected tenant not found.', 'error')
                return redirect(url_for('properties.html'))

            # Ensure the tenant isn't linked to another unit (vacate previous unit)
            cur.execute("""
                UPDATE units
                SET tenant_id = NULL,
                    status = CASE WHEN status = 'Occupied' THEN 'Vacant' ELSE status END
                WHERE tenant_id = %s AND id <> %s
            """, (tenant_id, unit_id))

            # Keep tenant record aligned with this unit
            cur.execute("""
                UPDATE tenants
                SET property_id = %s,
                    unit_id = %s,
                    unit = %s,
                    amount = %s
                WHERE id = %s
            """, (property_id, unit_id, unit_number, rent, tenant_id))

            # Prevent inconsistent "Vacant" status when a tenant is assigned
            if status != 'Maintenance':
                status = 'Occupied'
        else:
            # If no tenant selected, avoid "Occupied" without a tenant
            if status == 'Occupied':
                status = 'Vacant'

        cur.execute("""
            UPDATE units
            SET unit_number = %s,
                floor = %s,
                type = %s,
                status = %s,
                rent = %s,
                tenant_id = %s
            WHERE id = %s
        """, (unit_number, floor, unit_type, status, rent, tenant_id, unit_id))
        conn.commit()
        flash('Unit updated successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating unit: {str(e)}', 'error')
    finally:
        cur.close()
        if should_close:
            conn.close()

    return redirect(url_for('properties.html'))
