import os
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent / 'django_arms'
sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_arms.settings_prod')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
