import os

import dj_database_url

from .settings import *

DEBUG = os.environ.get('DEBUG', 'False').lower() in ('1', 'true', 'yes')

# Sensitive settings from environment variables with safe production fallbacks
secret_key = os.environ.get('SECRET_KEY')
if secret_key:
    SECRET_KEY = secret_key
elif 'SECRET_KEY' in globals() and SECRET_KEY:
    pass
else:
    SECRET_KEY = 'django-insecure-arms-prod-stable-fallback-key-2026'

allowed_hosts = os.environ.get('ALLOWED_HOSTS')
if allowed_hosts:
    ALLOWED_HOSTS = [host.strip() for host in allowed_hosts.split(',') if host.strip()]
else:
    ALLOWED_HOSTS = ['*']

# Database configuration: connect via DATABASE_URL if provided, else keep base database
database_url = os.environ.get('DATABASE_URL')
if database_url:
    DATABASES['default'] = dj_database_url.parse(database_url, conn_max_age=600)

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = [
    'https://*.onrender.com',
    'https://arms-2-0-web.onrender.com',
    'http://localhost:8001',
    'http://127.0.0.1:8001',
]
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False').lower() in ('1', 'true', 'yes')
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    os.environ.get('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False').lower()
    in ('1', 'true', 'yes')
)
SECURE_HSTS_PRELOAD = (
    os.environ.get('SECURE_HSTS_PRELOAD', 'False').lower()
    in ('1', 'true', 'yes')
)
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'