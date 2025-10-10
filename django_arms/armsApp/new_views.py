# views.py - Fixed version
import datetime
from django.shortcuts import redirect, render
import json
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpResponse
from armsApp import models, forms
from django.db.models import Q
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required


def context_data():
    context = {
        'page_name': '',
        'page_title': '',
        'system_name': 'Airlines Reservation Management System',
        'topbar': True,
        'footer': True,
    }
    return context


def landing_page(request):
    context = context_data()
    context['topbar'] = False
    context['footer'] = False
    context['page_title'] = "Welcome to Airline Reservation System"
    if request.user.is_authenticated:
        try:
            if request.user.profile.is_admin:
                return redirect("home-page")
            else:
                return redirect("user-dashboard")
        except:
            return redirect("user-dashboard")
    return render(request, 'landing.html', context)
