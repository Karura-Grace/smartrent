# config.py
import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = 'smartrent-secret-key-2024'
    MYSQL_HOST = '127.0.0.1'
    MYSQL_USER = 'root'
    MYSQL_PORT = 3306
    MYSQL_PASSWORD = ''
    MYSQL_DB = 'smartrent'
    MYSQL_CURSORCLASS = 'DictCursor'
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'properties')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

    PAYHERO_USERNAME = os.getenv('PAYHERO_USERNAME')
    PAYHERO_PASSWORD = os.getenv('PAYHERO_PASSWORD')
    PAYHERO_CHANNEL_ID = os.getenv('PAYHERO_CHANNEL_ID')
    PAYHERO_CALLBACK_URL = os.getenv('PAYHERO_CALLBACK_URL')