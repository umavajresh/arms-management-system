import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .settings import *

SECRET_KEY = os.environ.get('SECRET_KEY', SECRET_KEY)
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('1', 'true', 'yes')

allowed_hosts = os.environ.get('ALLOWED_HOSTS')
if allowed_hosts:
    ALLOWED_HOSTS = [host.strip() for host in allowed_hosts.split(',') if host.strip()]

database_url = os.environ.get('DATABASE_URL')
if database_url:
    DATABASES['default'] = dj_database_url.parse(database_url, conn_max_age=600)
elif not DEBUG:
    raise ImproperlyConfigured('DATABASE_URL must be set when DEBUG is False.')

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'