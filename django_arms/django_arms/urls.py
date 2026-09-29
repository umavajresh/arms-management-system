"""
django_arms URL Configuration

The `urlpatterns` list routes URLs to views.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from armsApp.admin import admin_site

urlpatterns = [
    # Custom Admin Panel
    path('admin/', admin_site.urls),

    # Main Application URLs
    path('', include('armsApp.urls')),

    # CAPTCHA URLs
    path('captcha/', include('captcha.urls')),
]

# Serve media and static files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)