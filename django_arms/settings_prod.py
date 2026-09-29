from .settings import *
import os

# Override sensitive settings from environment variables
SECRET_KEY = os.environ.get('SECRET_KEY', SECRET_KEY)
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('1', 'true', 'yes')

# ALLOWED_HOSTS can be provided as comma-separated list in env
allowed = os.environ.get('ALLOWED_HOSTS')
if allowed:
    ALLOWED_HOSTS = [h.strip() for h in allowed.split(',') if h.strip()]

# Database configuration via DATABASE_URL (optional)
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Use dj-database-url if available
    try:
        import dj_database_url
        DATABASES['default'] = dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    except Exception:
        pass

# Security headers recommended for production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = 'DENY'
