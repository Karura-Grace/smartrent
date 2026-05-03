import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = 'smartrent-secret-key-2024'

    # MySQL Configuration
    MYSQL_HOST     = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_USER     = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DB       = os.getenv('MYSQL_DB', 'smartrent')
    MYSQL_CURSORCLASS = 'DictCursor'

    # SQLAlchemy (connects to the same MySQL DB you manage in phpMyAdmin)
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
        f"@{MYSQL_HOST}/{MYSQL_DB}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
    }

    PAYHERO_USERNAME   = os.getenv('PAYHERO_USERNAME')
    PAYHERO_PASSWORD   = os.getenv('PAYHERO_PASSWORD')
    PAYHERO_CHANNEL_ID = os.getenv('PAYHERO_CHANNEL_ID')
    PAYHERO_CALLBACK_URL = os.getenv('PAYHERO_CALLBACK_URL')
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
