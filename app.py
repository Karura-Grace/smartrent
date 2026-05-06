import os
from flask import Flask, render_template
from config import Config
from extensions import mysql, ensure_lease_tables, ensure_units_tenant_column, ensure_units_tenant_fk, ensure_payments_due_date_penalty_columns, ensure_transactions_table


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

    # Initialize extensions
    mysql.init_app(app)
    # Best-effort DB bootstrap for new tables
    ensure_lease_tables()
    ensure_units_tenant_column()
    ensure_units_tenant_fk()
    ensure_payments_due_date_penalty_columns()
    ensure_transactions_table()

    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # -------------------------
    # LANDING PAGE
    # -------------------------
    @app.route('/')
    def landing():
        return render_template('landingpage.html')

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

