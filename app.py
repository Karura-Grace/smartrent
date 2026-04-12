import os
from flask import Flask, render_template
from config import Config
from extensions import mysql


# Blueprint imports
from blueprints.auth import auth_bp
from blueprints.landlord import landlord_bp
from blueprints.tenant import tenant_bp
from blueprints.service import service_bp
from blueprints.properties import properties_bp
from blueprints.reports import reports_bp




def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialise extensions
    mysql.init_app(app)

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
    app.register_blueprint(landlord_bp)
    app.register_blueprint(tenant_bp)
    app.register_blueprint(service_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(reports_bp)

    return app


if __name__ == '__main__':
    create_app().run(debug=True)