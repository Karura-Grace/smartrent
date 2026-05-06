import os
import secrets
from flask import Flask, render_template, session, jsonify
from config import Config
from extensions import mysql, ensure_lease_tables, ensure_units_tenant_column, ensure_units_tenant_fk, ensure_payments_due_date_penalty_columns, ensure_transactions_table, ensure_maintenance_assigned_to_column, ensure_lease_tenant_signature_columns, ensure_bills_amount_paid_column, get_conn_and_cursor
from flask_session import Session


from blueprints.auth import auth_bp
from blueprints.agent import agent_bp
from blueprints.landlord import landlord_bp
from blueprints.tenant import tenant_bp
from blueprints.service import service_bp
from blueprints.properties import properties_bp
from blueprints.reports import reports_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Server-side filesystem sessions — each browser gets its own session file
    # so multiple tabs in different profiles/incognito windows are fully independent
    session_dir = os.path.join(os.path.dirname(__file__), 'flask_sessions')
    os.makedirs(session_dir, exist_ok=True)
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = session_dir
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    Session(app)

    # Initialize extensions
    mysql.init_app(app)
    # Best-effort DB bootstrap for new tables
    ensure_lease_tables()
    ensure_units_tenant_column()
    ensure_units_tenant_fk()
    ensure_payments_due_date_penalty_columns()
    ensure_transactions_table()
    ensure_maintenance_assigned_to_column()
    ensure_lease_tenant_signature_columns()
    ensure_bills_amount_paid_column()

    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # -------------------------
    # LANDING PAGE
    # -------------------------
    @app.route('/')
    def landing():
        return render_template('landingpage.html')

    # -------------------------
    # NOTIFICATIONS API
    # -------------------------
    @app.route('/api/notifications')
    def api_notifications():
        user_id = session.get('user_id')
        role    = (session.get('role') or '').lower()
        if not user_id:
            return jsonify({'notifications': []})
        try:
            conn, cur, should_close = get_conn_and_cursor()
            notifications = []
            if role == 'tenant':
                # Fetch latest notices for the tenant's property
                cur.execute("""
                    SELECT n.title, n.message, n.type, n.created_at AS sent_at
                    FROM notices n
                    JOIN tenant t ON t.property_id = n.property_id
                    WHERE t.id = %s
                    ORDER BY n.created_at DESC LIMIT 5
                """, (user_id,))
            elif role == 'landlord':
                # Latest notices the landlord sent
                cur.execute("""
                    SELECT title, message, type, created_at AS sent_at
                    FROM notices WHERE sender_id = %s
                    ORDER BY created_at DESC LIMIT 5
                """, (user_id,))
            elif role == 'agent':
                cur.execute("""
                    SELECT title, message, type, created_at AS sent_at
                    FROM notices WHERE sender_id = %s
                    ORDER BY created_at DESC LIMIT 5
                """, (user_id,))
            else:
                cur.close()
                if should_close: conn.close()
                return jsonify({'notifications': []})

            for row in cur.fetchall():
                r = dict(row)
                r['sent_at'] = str(r.get('sent_at') or '')[:16]
                notifications.append(r)
            cur.close()
            if should_close: conn.close()
            return jsonify({'notifications': notifications})
        except Exception:
            return jsonify({'notifications': []})

    # -------------------------
    # REGISTER BLUEPRINTS
    # -------------------------
    app.register_blueprint(auth_bp)
    app.register_blueprint(agent_bp)
    app.register_blueprint(landlord_bp)
    app.register_blueprint(tenant_bp)
    app.register_blueprint(service_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(reports_bp)
   
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)# config.py

