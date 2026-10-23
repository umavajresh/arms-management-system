import datetime
import json
import logging
import os

import requests
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q, Min, Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from armsApp import models, forms

from armsApp.utils import context_data
from armsApp.ai_chatbot import (
    get_travel_response,
    extract_travel_preferences,
    search_real_flights,
)
logger = logging.getLogger(__name__)


def _flight_seat_inventory(flight):
    inventory = {}
    for seat_type, seat_class, prefix, capacity, letters in (
        ('1', 'business', 'B', flight.business_class_slots, 'ABCD'),
        ('2', 'economy', 'E', flight.economy_slots, 'ABCDEF'),
    ):
        for index in range(max(0, capacity)):
            row, letter_index = divmod(index, len(letters))
            seat = f"{prefix}{row + 1}{letters[letter_index]}"
            inventory[seat] = {'type': seat_type, 'class': seat_class}
    return inventory


def landing_page(request):
    # Clear any potential cache data
    if not request.user.is_authenticated:
        request.session.flush()
    
    context = context_data()
    context['topbar'] = False
    context['footer'] = False
    context['page_title'] = "Welcome to Airline Reservation System"
    
    if request.user.is_authenticated:
        try:
            # Check user role and redirect appropriately
            from armsApp.models import UserProfile
            try:
                profile = UserProfile.objects.get(user=request.user)
                if profile.user_type == 'admin':
                    return redirect("home-page")  # Admin dashboard
                else:
                    return redirect("user-dashboard")  # Regular user dashboard
            except UserProfile.DoesNotExist:
                # Create a default profile for the user
                profile = UserProfile.objects.create(
                    user=request.user,
                    custom_id=f"UID{request.user.id}",
                    mobile="",
                    is_admin=False,
                    user_type='user'  # Default to regular user
                )
                return redirect("user-dashboard")
        except Exception as e:
            logger.exception("Error in landing page")
            # Default to user dashboard on error
            return redirect("user-dashboard")
    
    # For non-authenticated users, show the landing page
    return render(request, 'landing.html', context)

def user_dashboard(request):
    if not request.user.is_authenticated:
        messages.error(request, "Please log in to access your dashboard")
        return redirect("login-page")
    
    context = context_data()
    context['page_title'] = "User Dashboard"
    
    try:
        # Try to get user profile, create if it doesn't exist
        try:
            profile = request.user.profile
        except:
            from armsApp.models import UserProfile
            profile = UserProfile.objects.create(
                user=request.user,
                custom_id=f"UID{request.user.id}",
                mobile=""
            )
        
        # Get recent searches if implemented
        context['recent_searches'] = []
        
        # Get user's reservations
        from armsApp.models import Reservation, UserNotification
        reservations = Reservation.objects.filter(user=request.user).order_by('-date_added')[:3]
        context['recent_reservations'] = reservations
        
        # Get unread notifications
        notifications = UserNotification.objects.filter(user=request.user, is_read=False).order_by('-created_at')[:5]
        context['notifications'] = notifications
        
        return render(request, 'user_dashboard.html', context)
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect("login-page")

def user_reservations(request):
    context = context_data()
    context['page_title'] = "My Reservations"
    
    if request.user.is_authenticated:
        # Get reservations for current user
        reservations = models.Reservation.objects.filter(user=request.user).order_by('-date_added')
        context['reservations'] = reservations
        return render(request, 'user_reservations.html', context)
    else:
        return redirect("login-page")

def cancel_reservation(request):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'A POST request is required.'},
            status=405,
        )
    if not request.user.is_authenticated:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Please sign in to cancel a reservation.'},
            status=401,
        )

    reservation_id = request.POST.get('id', '')
    if not reservation_id.isdecimal():
        return JsonResponse(
            {'status': 'failed', 'msg': 'A valid reservation is required.'},
            status=400,
        )

    try:
        with transaction.atomic():
            reservation = models.Reservation.objects.select_for_update().get(
                pk=reservation_id,
                user=request.user,
            )
            if not reservation.can_cancel():
                return JsonResponse(
                    {'status': 'failed', 'msg': reservation.get_cancellation_status()},
                    status=409,
                )
            reservation.status = '2'
            reservation.save(update_fields=['status'])
    except models.Reservation.DoesNotExist:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Reservation not found or unavailable.'},
            status=404,
        )
    except Exception:
        logger.exception(
            "Failed to cancel reservation %s for user %s",
            reservation_id,
            request.user.pk,
        )
        return JsonResponse(
            {'status': 'failed', 'msg': 'Unable to cancel the reservation.'},
            status=500,
        )

    return JsonResponse(
        {'status': 'success', 'msg': 'Reservation successfully cancelled.'}
    )

def seat_selection(request, pk=None):
    context = context_data()
    context['page_title'] = "Select Your Seat"
    
    # Check if pk is provided
    if pk is None:
        messages.error(request, "Invalid Flight ID")
        return redirect('public-page')
    
    try:
        # Get the flight details
        flight = models.Flights.objects.get(id=pk)
        
        # Check if flight has already departed
        from django.utils import timezone
        current_time = timezone.now()
        
        if flight.departure <= current_time:
            messages.error(request, "This flight has already departed. You cannot select seats for a past flight.")
            return redirect('search-flight')
            
        context['flight'] = flight
        
    except models.Flights.DoesNotExist:
        messages.error(request, "Flight not found")
        return redirect('public-page')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('public-page')
    
    inventory = _flight_seat_inventory(flight)
    reserved_seats = set(
        models.Reservation.objects.filter(
            flight=flight,
            status__in=['0', '1'],
            seat_number__in=inventory,
        ).values_list('seat_number', flat=True)
    )
    business_seats = [
        {'seat': seat, 'available': seat not in reserved_seats}
        for seat, details in inventory.items()
        if details['type'] == '1'
    ]
    economy_seats = [
        {'seat': seat, 'available': seat not in reserved_seats}
        for seat, details in inventory.items()
        if details['type'] == '2'
    ]
    
    context['business_seats'] = business_seats
    context['economy_seats'] = economy_seats
    
    if request.method == 'POST':
        try:
            # Process the multi-seat selection
            import json
            
            selected_seats_data = request.POST.get('selected_seats')
            
            if not selected_seats_data:
                messages.error(request, "Please select your seats and passenger count")
                return render(request, 'seat_selection.html', context)
            
            # Parse and validate the submitted seats against the flight inventory.
            try:
                seats_info = json.loads(selected_seats_data)
            except (json.JSONDecodeError, TypeError):
                messages.error(request, "Invalid seat selection data. Please try again.")
                return render(request, 'seat_selection.html', context)

            if not isinstance(seats_info, dict):
                messages.error(request, "Invalid seat selection data. Please try again.")
                return render(request, 'seat_selection.html', context)

            selected_seats = seats_info.get('seats')
            passenger_count = seats_info.get('passenger_count')
            if (
                not isinstance(selected_seats, list)
                or type(passenger_count) is not int
                or not 1 <= passenger_count <= 6
                or len(selected_seats) != passenger_count
            ):
                messages.error(request, "Select between one and six seats, one for each passenger.")
                return render(request, 'seat_selection.html', context)

            canonical_seats = []
            unavailable_seats = set()
            selected_seat_codes = set()
            for seat_info in selected_seats:
                if not isinstance(seat_info, dict):
                    messages.error(request, "Invalid seat selection data. Please try again.")
                    return render(request, 'seat_selection.html', context)

                seat_number = seat_info.get('seat')
                seat = inventory.get(seat_number) if isinstance(seat_number, str) else None
                if (
                    seat is None
                    or seat_info.get('class') != seat['class']
                    or seat_number in selected_seat_codes
                ):
                    messages.error(request, "One or more selected seats are invalid.")
                    return render(request, 'seat_selection.html', context)

                selected_seat_codes.add(seat_number)
                canonical_seats.append({
                    'seat': seat_number,
                    'type': seat['type'],
                    'class': seat['class'],
                })

                if seat_number in reserved_seats:
                    unavailable_seats.add(seat_number)

            if unavailable_seats:
                messages.error(
                    request,
                    "Some selected seats are no longer available. Please select different seats.",
                )
                return render(request, 'seat_selection.html', context)

            request.session['selected_flight'] = str(pk)
            request.session['selected_seats_data'] = json.dumps({
                'passenger_count': passenger_count,
                'seats': canonical_seats,
            })
            request.session['passenger_count'] = passenger_count

            try:
                return redirect('reserve-form', pk=pk)
            except Exception as e:
                logger.exception("Redirect error during seat selection")
                messages.error(request, "Unable to continue to the reservation form.")
                return render(request, 'seat_selection.html', context)
            
        except Exception as e:
            logger.exception("Seat selection error")
            messages.error(request, f"An error occurred: {str(e)}")
            return render(request, 'seat_selection.html', context)

    return render(request, 'seat_selection.html', context)
    
def userregister(request):
    context = context_data()
    context['topbar'] = False
    context['footer'] = False
    context['page_title'] = "User Registration"
    context['reg_form'] = forms.SaveUser() # Initialize an empty form
    if request.user.is_authenticated:
        return redirect("home-page")
    return render(request, 'register.html', context)

@login_required
def upload_modal(request):
    context = context_data()
    return render(request, 'upload.html', context)

def save_register(request):
    resp={'status':'failed', 'msg':''}
    try:
        if not request.method == 'POST':
            resp['msg'] = "No data has been sent on this request"
            return HttpResponse(json.dumps(resp), content_type="application/json")
        
        # Explicitly check if required fields are in request.POST
        required_fields = ['custom_id', 'mobile', 'username', 'email', 'first_name', 'last_name', 'password1', 'password2']
        missing_fields = [field for field in required_fields if field not in request.POST or not request.POST.get(field)]
        
        if missing_fields:
            resp['msg'] = f"The following fields are required: {', '.join(missing_fields)}"
            return HttpResponse(json.dumps(resp), content_type="application/json")
        
        # Check if passwords match (additional validation)
        if request.POST.get('password1') != request.POST.get('password2'):
            resp['msg'] = "Passwords do not match."
            return HttpResponse(json.dumps(resp), content_type="application/json")
                
        # Create and validate the form
        form = forms.SaveUser(request.POST)
        
        if form.is_valid():
            try:
                from armsApp.models import UserProfile

                with transaction.atomic():
                    user = form.save()
                    profile = UserProfile.objects.create(
                        user=user,
                        custom_id=form.cleaned_data['custom_id'],
                        mobile=form.cleaned_data['mobile'],
                        is_admin=False,
                        user_type='user',
                        security_question=form.cleaned_data['security_question'],
                        security_answer=make_password(form.cleaned_data['security_answer']),
                        date_of_birth=form.cleaned_data['date_of_birth'],
                    )
            except Exception:
                logger.exception("Registration error during save_register")
                resp['msg'] = "Your account could not be saved. Please check your details and try again."
            else:
                messages.success(request, "Your Account has been created successfully")
                resp['status'] = 'success'
                resp['msg'] = "Registration successful! Redirecting to login page."
        else:
            logger.debug("Form errors: %s", form.errors)
            error_messages = []
            for field_name, error_list in form.errors.items():
                for error in error_list:
                    error_messages.append(f"[{field_name}] {error}")
            
            resp['msg'] = "; ".join(error_messages)
            if not resp['msg']:
                resp['msg'] = "Form validation failed. Please check all fields and try again."
    except Exception:
        logger.exception("Unexpected error in save_register")
        resp['msg'] = "An unexpected error occurred. Please try again."
    
    # Ensure the return statement is always executed
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def update_profile(request):
    context = context_data()
    context['page_title'] = 'Update Profile'
    user = User.objects.get(id = request.user.id)
    
        # Get or create user profile
    try:
        profile = user.profile
    except:
        from armsApp.models import UserProfile
        profile = UserProfile.objects.create(
            user=user,
            custom_id=f"UID{user.id}",
            mobile="",
            user_type='user',  # Default to regular user
            is_admin=False
        )
        
    if not request.method == 'POST':
        form = forms.UpdateProfile(instance=user)
        context['form'] = form
        context['profile'] = profile
    else:
        form = forms.UpdateProfile(request.POST, instance=user)
        if form.is_valid():
            form.save()
            
            # Update user profile fields if provided
            if 'custom_id' in request.POST and request.POST['custom_id']:
                profile.custom_id = request.POST['custom_id']
            if 'mobile' in request.POST and request.POST['mobile']:
                profile.mobile = request.POST['mobile']
                
            # Keep user type the same - don't allow changing through normal profile update
            profile.save()
            
            messages.success(request, "Profile has been updated")
            return redirect("profile-page")
        else:
            context['form'] = form
            context['profile'] = profile
            
    return render(request, 'manage_profile.html',context)

@login_required
def update_password(request):
    context =context_data()
    context['page_title'] = "Update Password"
    if request.method == 'POST':
        form = forms.UpdatePasswords(user = request.user, data= request.POST)
        if form.is_valid():
            form.save()
            messages.success(request,"Your Account Password has been updated successfully")
            update_session_auth_hash(request, form.user)
            return redirect("profile-page")
        else:
            context['form'] = form
    else:
        form = forms.UpdatePasswords(request.POST)
        context['form'] = form
    return render(request,'update_password.html',context)

# Create your views here.
def login_page(request):
    context = context_data()
    context['topbar'] = False
    context['footer'] = False
    context['page_name'] = 'login'
    context['page_title'] = 'Login'
    return render(request, 'login.html', context)

def login_user(request):
    resp = {"status": 'failed', 'msg': '', 'redirect': ''}
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''

        if not username or not password:
            resp['msg'] = "Enter your User ID or username and password"
            return HttpResponse(json.dumps(resp), content_type='application/json')

        from armsApp.models import UserProfile
        profile = UserProfile.objects.filter(custom_id=username).select_related('user').first()
        auth_username = profile.user.username if profile else username
        user = authenticate(request, username=auth_username, password=password)
            
        if user is not None:
            if user.is_active:
                user_profile = getattr(user, 'profile', None)
                if not user_profile:
                    try:
                        user_profile = UserProfile.objects.get(user=user)
                    except UserProfile.DoesNotExist:
                        user_profile = None

                if user_profile and user_profile.two_factor_enabled:
                    otp_code = user_profile.generate_otp()
                    request.session['2fa_user_id'] = user.id
                    request.session['2fa_attempts'] = 0
                    logger.info("2FA OTP generated for user %s: %s", user.username, otp_code)
                    resp['status'] = '2fa_required'
                    resp['redirect'] = reverse('verify-2fa')
                    return HttpResponse(json.dumps(resp), content_type='application/json')

                login(request, user)
                resp['status'] = 'success'
                
                # Direct redirect based on user type
                try:
                    if user_profile and user_profile.user_type == 'admin':
                        resp['redirect'] = '/home'  # Admin dashboard
                    else:
                        resp['redirect'] = '/user_dashboard'  # Regular user dashboard
                except Exception:
                    # If no profile exists yet, redirect to user dashboard
                    resp['redirect'] = '/user_dashboard'
            else:
                resp['msg'] = "Account is inactive"
        else:
            resp['msg'] = "Incorrect User ID or password"
    return HttpResponse(json.dumps(resp), content_type='application/json')


def verify_2fa(request):
    if request.user.is_authenticated:
        try:
            if request.user.profile.user_type == 'admin':
                return redirect('home-page')
        except Exception:
            pass
        return redirect('user-dashboard')

    user_id = request.session.get('2fa_user_id')
    if not user_id:
        messages.error(request, "Your two-factor verification session has expired. Please sign in again.")
        return redirect('login-page')

    from armsApp.models import UserProfile
    from django.contrib.auth.models import User

    user = User.objects.filter(id=user_id, is_active=True).first()
    if not user:
        request.session.pop('2fa_user_id', None)
        request.session.pop('2fa_attempts', None)
        messages.error(request, "User account not found. Please sign in again.")
        return redirect('login-page')

    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        request.session.pop('2fa_user_id', None)
        request.session.pop('2fa_attempts', None)
        messages.error(request, "User profile not found. Please sign in again.")
        return redirect('login-page')

    context = context_data()
    context['page_title'] = "Two-Factor Verification"
    context['topbar'] = False
    context['footer'] = False
    context['verify_username'] = user.username
    if user.email and '@' in user.email:
        name_part, domain_part = user.email.split('@', 1)
        masked_name = name_part[0] + '***' if len(name_part) > 1 else '***'
        context['masked_email'] = f"{masked_name}@{domain_part}"
    else:
        context['masked_email'] = None

    if request.method == 'POST':
        attempts = request.session.get('2fa_attempts', 0) + 1
        request.session['2fa_attempts'] = attempts

        if attempts > 5:
            request.session.pop('2fa_user_id', None)
            request.session.pop('2fa_attempts', None)
            messages.error(request, "Too many failed verification attempts. Please sign in again.")
            return redirect('login-page')

        otp_code = (request.POST.get('otp_code') or '').strip()
        if not otp_code:
            messages.error(request, "Please enter the 6-digit verification code.")
            return render(request, 'verify_2fa.html', context)

        if profile.verify_otp(otp_code):
            request.session.pop('2fa_user_id', None)
            request.session.pop('2fa_attempts', None)
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or user.username}. Two-factor authentication verified.")
            if profile.user_type == 'admin':
                return redirect('home-page')
            return redirect('user-dashboard')
        else:
            messages.error(request, "Invalid or expired verification code. Please check and try again.")
            return render(request, 'verify_2fa.html', context)

    return render(request, 'verify_2fa.html', context)


def resend_2fa_otp(request):
    user_id = request.session.get('2fa_user_id')
    if not user_id:
        messages.error(request, "Your two-factor verification session has expired.")
        return redirect('login-page')

    from django.contrib.auth.models import User
    user = User.objects.filter(id=user_id, is_active=True).first()
    if not user:
        request.session.pop('2fa_user_id', None)
        return redirect('login-page')

    profile = getattr(user, 'profile', None)
    if profile:
        profile.generate_otp()
        messages.info(request, "A new 6-digit verification code has been generated.")
    return redirect('verify-2fa')


@login_required
def toggle_2fa(request):
    if request.method == 'POST':
        from armsApp.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(
            user=request.user,
            defaults={'custom_id': f"UID{request.user.id}", 'mobile': ''}
        )
        profile.two_factor_enabled = not profile.two_factor_enabled
        if not profile.two_factor_enabled:
            profile.clear_otp()
        profile.save(update_fields=['two_factor_enabled'])

        status_text = "enabled" if profile.two_factor_enabled else "disabled"
        messages.success(request, f"Two-factor authentication has been {status_text} for your account.")
    return redirect('profile-page')

def search_flight(request):
    context = context_data()
    context['page'] = 'Search Available Flight'
    airlines = models.Airlines.objects.filter(delete_flag = 0, status = 1).all()
    airports = models.Airport.objects.filter(delete_flag = 0, status = 1).all()
    context['airlines'] = airlines
    context['airports'] = airports
    
    return render(request,'search_flight.html', context)

def _flight_tracking_data(flight, current_time=None):
    current_time = current_time or timezone.now()
    departure = flight.departure
    arrival = flight.estimated_arrival
    total_seconds = max((arrival - departure).total_seconds(), 1)

    if current_time < departure - datetime.timedelta(hours=2):
        status = 'Scheduled'
        progress = 0
    elif current_time < departure:
        status = 'Boarding'
        progress = 0
    elif current_time < arrival:
        status = 'In flight'
        progress = min(99, max(1, round((current_time - departure).total_seconds() / total_seconds * 100)))
    else:
        status = 'Landed'
        progress = 100

    return {
        'id': flight.id,
        'code': flight.code,
        'airline': flight.airline.name,
        'from_code': flight.from_airport.code,
        'from_name': flight.from_airport.name,
        'to_code': flight.to_airport.code,
        'to_name': flight.to_airport.name,
        'departure': timezone.localtime(departure).isoformat(),
        'arrival': timezone.localtime(arrival).isoformat(),
        'status': status,
        'progress': progress,
        'updated_at': timezone.localtime(current_time).isoformat(),
    }

def _fetch_opensky_flight_data(flight_code):
    code = (flight_code or '').strip().upper().replace(' ', '')
    if not code:
        return None

    try:
        response = requests.get(
            'https://opensky-network.org/api/states/all',
            params={
                'time': int(timezone.now().timestamp()),
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json() or {}
        states = payload.get('states') or []

        for state in states:
            if len(state) < 2:
                continue
            callsign = (state[1] or '').strip().upper().replace(' ', '')
            if not callsign or callsign != code and not callsign.startswith(code):
                continue

            latitude = state[6]
            longitude = state[5]
            if latitude is None or longitude is None:
                continue

            velocity = state[9]
            altitude = state[7]
            return {
                'flight_code': code,
                'airline': 'OpenSky Network',
                'from_code': '',
                'from_name': 'Live airspace position',
                'to_code': '',
                'to_name': 'Live tracking data',
                'departure': None,
                'arrival': None,
                'status': 'Live airborne',
                'latitude': latitude,
                'longitude': longitude,
                'altitude': altitude,
                'speed_horizontal': velocity,
                'updated_at': timezone.now().isoformat(),
                'source': 'opensky',
                'progress': 50,
            }
    except requests.RequestException:
        logger.exception('OpenSky live flight lookup failed for %s', flight_code)
    except ValueError:
        logger.exception('OpenSky returned invalid JSON for %s', flight_code)

    return None


def _fetch_live_flight_data(flight_code):
    api_key = os.getenv('AVIATIONSTACK_API_KEY')
    if api_key:
        try:
            response = requests.get(
                'http://api.aviationstack.com/v1/flights',
                params={
                    'access_key': api_key,
                    'flight_iata': flight_code,
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json() or {}
            records = payload.get('data') or []
            if records:
                item = records[0]
                flight = item.get('flight') or {}
                airline = item.get('airline') or {}
                departure = item.get('departure') or {}
                arrival = item.get('arrival') or {}
                live = item.get('live') or {}

                flight_code_value = (flight.get('iata') or flight.get('icao') or flight_code or '').upper()
                departure_time = departure.get('scheduled') or departure.get('estimated') or departure.get('actual')
                arrival_time = arrival.get('scheduled') or arrival.get('estimated') or arrival.get('actual')
                updated_time = live.get('updated') or timezone.now().isoformat()

                return {
                    'flight_code': flight_code_value,
                    'airline': airline.get('name') or 'Unknown airline',
                    'from_code': (departure.get('iata') or departure.get('icao') or '').upper(),
                    'from_name': departure.get('airport') or 'Unknown origin',
                    'to_code': (arrival.get('iata') or arrival.get('icao') or '').upper(),
                    'to_name': arrival.get('airport') or 'Unknown destination',
                    'departure': departure_time,
                    'arrival': arrival_time,
                    'status': item.get('flight_status') or item.get('status') or 'Unknown',
                    'latitude': live.get('latitude'),
                    'longitude': live.get('longitude'),
                    'altitude': live.get('altitude'),
                    'speed_horizontal': live.get('speed_horizontal'),
                    'updated_at': updated_time,
                    'source': 'aviationstack',
                }
        except requests.RequestException:
            logger.exception('AviationStack live flight lookup failed for %s', flight_code)
        except ValueError:
            logger.exception('AviationStack returned invalid JSON for %s', flight_code)

    return _fetch_opensky_flight_data(flight_code)


def flight_tracker(request):
    context = context_data()
    context['page_title'] = 'Live Flight Tracker'
    context['tracked_code'] = request.GET.get('flight', '').strip()
    current_time = timezone.now()
    context['recent_flights'] = models.Flights.objects.filter(
        delete_flag=0,
        estimated_arrival__gte=current_time - datetime.timedelta(days=1),
        departure__lte=current_time + datetime.timedelta(days=7),
    ).select_related('from_airport', 'to_airport').order_by('departure')[:8]
    return render(request, 'flight_tracker.html', context)


def flight_tracking_api(request):
    code = request.GET.get('flight', '').strip()
    if not code:
        return JsonResponse({'error': 'Enter a flight code to track.'}, status=400)

    live_data = _fetch_live_flight_data(code)
    if live_data:
        return JsonResponse({'flight': live_data})

    try:
        flight = models.Flights.objects.select_related(
            'airline', 'from_airport', 'to_airport'
        ).get(code__iexact=code, delete_flag=0)
    except models.Flights.DoesNotExist:
        return JsonResponse({'error': 'No active flight was found with that code.'}, status=404)

    return JsonResponse({'flight': _flight_tracking_data(flight)})

def search_result(request, fromA=None, toA=None, departure = None):
    context = context_data()
    context['page'] = 'Search Result'
    
    # Store search parameters in context for filter form
    context['from_airport'] = fromA
    context['to_airport'] = toA
    context['departure_date'] = departure
    
    # Get filter parameters
    price_sort = request.GET.get('price_sort', '')  # 'asc', 'desc', or ''
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    time_filter = request.GET.get('time_filter', '')  # 'morning', 'night', or ''
    
    # Store filter parameters in context to maintain state
    context['price_sort'] = price_sort
    context['min_price'] = min_price
    context['max_price'] = max_price
    context['time_filter'] = time_filter
    
    if fromA is None and toA is None and departure is None:
        messages.error(request, "Invalid Search Inputs")
        return redirect('public-page')
    else:
        departure = datetime.datetime.strptime(departure, "%Y-%m-%d")
        year = departure.strftime("%Y")
        month = departure.strftime("%m")
        day = departure.strftime("%d")
        
        # Base query with departure time validation
        from django.utils import timezone
        current_time = timezone.now()
        
        flights = models.Flights.objects.filter(
            delete_flag=0,
            from_airport=fromA,
            to_airport=toA,
            departure__year=year,
            departure__month=month,
            departure__day=day,
            departure__gt=current_time  # Only show flights that haven't departed yet
        )
        
        # Apply price filters if provided
        if min_price and min_price.isdigit():
            min_price = float(min_price)
            flights = flights.filter(Q(economy_price__gte=min_price) | Q(business_class_price__gte=min_price))
            
        if max_price and max_price.isdigit():
            max_price = float(max_price)
            flights = flights.filter(Q(economy_price__lte=max_price) | Q(business_class_price__lte=max_price))
        
        # Apply time filters
        if time_filter == 'morning':
            # Morning flights (6 AM to 12 PM)
            flights = flights.filter(departure__hour__gte=6, departure__hour__lt=12)
        elif time_filter == 'afternoon':
            # Afternoon flights (12 PM to 5 PM)
            flights = flights.filter(departure__hour__gte=12, departure__hour__lt=17)
        elif time_filter == 'evening':
            # Evening flights (5 PM to 9 PM)
            flights = flights.filter(departure__hour__gte=17, departure__hour__lt=21)
        elif time_filter == 'night':
            # Night flights (9 PM to 6 AM)
            flights = flights.filter(Q(departure__hour__gte=21) | Q(departure__hour__lt=6))
        
        # Apply sorting
        if price_sort == 'asc':
            # Sort by economy price (lowest first)
            flights = flights.order_by('economy_price')
        elif price_sort == 'desc':
            # Sort by economy price (highest first)
            flights = flights.order_by('-economy_price')
        else:
            # Default sort by departure time
            flights = flights.order_by('departure')
        
        # Store results in context
        context['flights'] = flights.all()
        
        # Get min and max prices for the price range slider
        if flights.exists():
            context['min_available_price'] = flights.aggregate(Min('economy_price'))['economy_price__min']
            context['max_available_price'] = flights.aggregate(Max('business_class_price'))['business_class_price__max']
        else:
            context['min_available_price'] = 0
            context['max_available_price'] = 1000
            
        return render(request, 'search_result.html', context)

def save_reservation(request):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'A POST request is required.'},
            status=405,
        )
    if not request.user.is_authenticated:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Please sign in before submitting a reservation.'},
            status=401,
        )

    verified_until = request.session.get('reservation_verified_until')
    if (
        not isinstance(verified_until, (int, float))
        or timezone.now().timestamp() >= verified_until
    ):
        request.session.pop('reservation_verified_until', None)
        return JsonResponse(
            {'status': 'failed', 'msg': 'Please complete password and security verification again.'},
            status=403,
        )

    flight_id = request.POST.get('flight', '')
    if not flight_id or str(request.session.get('selected_flight')) != flight_id:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Please select seats for this flight again.'},
            status=400,
        )
    try:
        flight = models.Flights.objects.get(pk=flight_id)
    except (models.Flights.DoesNotExist, ValueError, TypeError):
        return JsonResponse(
            {'status': 'failed', 'msg': 'The selected flight is unavailable.'},
            status=400,
        )

    inventory = _flight_seat_inventory(flight)
    selected_data = request.session.get('selected_seats_data')
    if selected_data:
        try:
            selection = json.loads(selected_data)
        except (json.JSONDecodeError, TypeError):
            selection = None

        count = selection.get('passenger_count') if isinstance(selection, dict) else None
        seat_items = selection.get('seats') if isinstance(selection, dict) else None
        try:
            submitted_count = int(request.POST.get('passenger_count', ''))
        except (TypeError, ValueError):
            submitted_count = None
        if (
            type(count) is not int
            or not 1 <= count <= 6
            or submitted_count != count
            or not isinstance(seat_items, list)
            or len(seat_items) != count
        ):
            return JsonResponse(
                {'status': 'failed', 'msg': 'Please select seats for all passengers again.'},
                status=400,
            )
    else:
        count = 1
        legacy_seat = request.session.get('selected_seat')
        legacy_type = request.session.get('selected_type')
        seat = inventory.get(legacy_seat) if isinstance(legacy_seat, str) else None
        if not seat or seat['type'] != legacy_type:
            return JsonResponse(
                {'status': 'failed', 'msg': 'Please select a valid seat again.'},
                status=400,
            )
        seat_items = [{
            'seat': legacy_seat,
            'type': legacy_type,
            'class': seat['class'],
        }]

    seen_seats = set()
    canonical_seats = []
    for index, seat_info in enumerate(seat_items):
        if not isinstance(seat_info, dict):
            return JsonResponse(
                {'status': 'failed', 'msg': 'The seat selection is invalid.'},
                status=400,
            )
        seat_number = seat_info.get('seat')
        seat = inventory.get(seat_number) if isinstance(seat_number, str) else None
        if (
            not seat
            or seat_info.get('type') != seat['type']
            or seat_info.get('class') != seat['class']
            or seat_number in seen_seats
        ):
            return JsonResponse(
                {'status': 'failed', 'msg': 'The seat selection is invalid.'},
                status=400,
            )
        seen_seats.add(seat_number)
        if selected_data and (
            request.POST.get(f'passenger_{index}_seat') != seat_number
            or request.POST.get(f'passenger_{index}_type') != seat['type']
        ):
            return JsonResponse(
                {'status': 'failed', 'msg': 'The passenger seat selection has changed. Please start again.'},
                status=400,
            )
        canonical_seats.append({
            'seat': seat_number,
            'type': seat['type'],
        })

    passenger_forms = []
    for index, seat in enumerate(canonical_seats):
        if selected_data:
            form_data = {
                'first_name': request.POST.get(f'passenger_{index}_first_name', ''),
                'middle_name': request.POST.get(f'passenger_{index}_middle_name', ''),
                'last_name': request.POST.get(f'passenger_{index}_last_name', ''),
                'gender': request.POST.get(f'passenger_{index}_gender', ''),
            }
        else:
            form_data = {
                'first_name': request.POST.get('first_name', ''),
                'middle_name': request.POST.get('middle_name', ''),
                'last_name': request.POST.get('last_name', ''),
                'gender': request.POST.get('gender', ''),
            }
        if form_data['gender'] not in {'Male', 'Female'}:
            return JsonResponse(
                {'status': 'failed', 'msg': f'Please enter valid details for Passenger {index + 1}.'},
                status=400,
            )
        form_data.update({
            'flight': str(flight.pk),
            'type': seat['type'],
            'seat_number': seat['seat'],
            'email': request.POST.get('email', ''),
            'contact': request.POST.get('contact', ''),
            'address': request.POST.get('address', ''),
        })
        form = forms.SaveReservation(data=form_data)
        if not form.is_valid():
            errors = ' '.join(
                f"{field}: {' '.join(error_list)}"
                for field, error_list in form.errors.items()
            )
            return JsonResponse(
                {'status': 'failed', 'msg': errors or 'Please check the reservation details.'},
                status=400,
            )
        reservation = form.save(commit=False)
        reservation.user = request.user
        reservation.status = '0'
        passenger_forms.append(reservation)

    try:
        with transaction.atomic():
            locked_flight = models.Flights.objects.select_for_update().get(pk=flight.pk)
            if locked_flight.departure <= timezone.now():
                return JsonResponse(
                    {'status': 'failed', 'msg': 'This flight has already departed.'},
                    status=400,
                )

            current_inventory = _flight_seat_inventory(locked_flight)
            if any(
                current_inventory.get(item.seat_number, {}).get('type') != item.type
                for item in passenger_forms
            ):
                return JsonResponse(
                    {'status': 'failed', 'msg': 'The selected seats are no longer valid.'},
                    status=409,
                )
            taken = set(
                models.Reservation.objects.filter(
                    flight=locked_flight,
                    status__in=['0', '1'],
                    seat_number__in=seen_seats,
                ).values_list('seat_number', flat=True)
            )
            if taken:
                return JsonResponse(
                    {'status': 'failed', 'msg': 'A selected seat is no longer available. Please choose another seat.'},
                    status=409,
                )

            for reservation in passenger_forms:
                reservation.flight = locked_flight
                reservation.save()
    except models.Flights.DoesNotExist:
        return JsonResponse(
            {'status': 'failed', 'msg': 'The selected flight is unavailable.'},
            status=400,
        )
    except Exception:
        logger.exception("Unable to save reservation")
        return JsonResponse(
            {'status': 'failed', 'msg': 'Unable to submit the reservation. Please try again.'},
            status=500,
        )

    for key in (
        'selected_seat',
        'selected_type',
        'selected_flight',
        'selected_seats_data',
        'passenger_count',
        'reservation_verified_until',
    ):
        request.session.pop(key, None)
    message = (
        "Your reservation has been submitted successfully. It is now pending admin approval."
        if count == 1
        else f"Your reservation for {count} passengers has been submitted successfully. It is now pending admin approval."
    )
    messages.success(request, message)
    return JsonResponse({'status': 'success', 'msg': message})

@login_required
def reserve_form(request, pk=None):
    context = context_data()
    context['page'] = 'Search Result'
    
    if pk is None:
        messages.error(request, "Invalid Flight ID")
        return redirect('public-page')
        
    try:
        # Get flight details
        flight = models.Flights.objects.get(id=pk)
        
        # Check if flight has already departed
        from django.utils import timezone
        current_time = timezone.now()
        
        if flight.departure <= current_time:
            messages.error(request, "This flight has already departed. You cannot make a reservation for a past flight.")
            return redirect('search-flight')
            
        context['flight'] = flight
        
        inventory = _flight_seat_inventory(flight)
        reserved_seats = set(
            models.Reservation.objects.filter(
                flight=flight,
                status__in=['0', '1'],
                seat_number__in=inventory,
            ).values_list('seat_number', flat=True)
        )

        selected_seats_data = request.session.get('selected_seats_data')
        passenger_count = request.session.get('passenger_count', 1)
        selected_flight = request.session.get('selected_flight')
        selected_seat = request.session.get('selected_seat')
        selected_type = request.session.get('selected_type')

        if selected_flight and str(selected_flight) == str(pk):
            if selected_seats_data:
                try:
                    seats_info = json.loads(selected_seats_data)
                except (json.JSONDecodeError, TypeError):
                    logger.exception("Error parsing seat selection data")
                    messages.error(request, "Invalid seat selection data. Please select seats again.")
                    return redirect('seat-selection', pk=pk)

                selected_seats = seats_info.get('seats') if isinstance(seats_info, dict) else None
                count = seats_info.get('passenger_count') if isinstance(seats_info, dict) else None
                if (
                    not isinstance(selected_seats, list)
                    or type(count) is not int
                    or count != passenger_count
                    or not 1 <= count <= 6
                    or len(selected_seats) != count
                ):
                    messages.error(request, "Invalid seat selection data. Please select seats again.")
                    return redirect('seat-selection', pk=pk)

                canonical_seats = []
                seen_seats = set()
                for seat_info in selected_seats:
                    if not isinstance(seat_info, dict):
                        messages.error(request, "Invalid seat selection data. Please select seats again.")
                        return redirect('seat-selection', pk=pk)
                    seat_number = seat_info.get('seat')
                    seat = inventory.get(seat_number) if isinstance(seat_number, str) else None
                    if (
                        seat is None
                        or seat_info.get('type') != seat['type']
                        or seat_info.get('class') != seat['class']
                        or seat_number in seen_seats
                        or seat_number in reserved_seats
                    ):
                        messages.error(request, "A selected seat is invalid or no longer available.")
                        return redirect('seat-selection', pk=pk)
                    seen_seats.add(seat_number)
                    class_name = "Business Class" if seat['type'] == '1' else "Economy"
                    seat_price = (
                        flight.business_class_price if seat['type'] == '1'
                        else flight.economy_price
                    )
                    canonical_seats.append({
                        'seat': seat_number,
                        'type': seat['type'],
                        'class': seat['class'],
                        'display_class': class_name,
                        'price': seat_price,
                    })

                context['selected_seats'] = canonical_seats
                context['passenger_count'] = count
                context['is_multi_passenger'] = True
                context['seat_details'] = [
                    {
                        'seat': item['seat'],
                        'class': item['display_class'],
                        'price': item['price'],
                    }
                    for item in canonical_seats
                ]
                context['total_price'] = sum(item['price'] for item in canonical_seats)
                context['reservation_payload'] = {
                    'passenger_count': count,
                    'is_multi_passenger': True,
                    'selected_seats': canonical_seats,
                }
            elif selected_seat and selected_type:
                seat = inventory.get(selected_seat)
                if (
                    seat is None
                    or selected_type != seat['type']
                    or selected_seat in reserved_seats
                ):
                    messages.error(request, "The selected seat is invalid or no longer available.")
                    return redirect('seat-selection', pk=pk)
                context['selected_seat'] = selected_seat
                context['selected_type'] = selected_type
                context['passenger_count'] = 1
                context['is_multi_passenger'] = False
                seat_class = "Business Class" if seat['type'] == '1' else "Economy"
                context['seat_class'] = seat_class
                context['seat_price'] = (
                    flight.business_class_price if seat['type'] == '1'
                    else flight.economy_price
                )
                context['reservation_payload'] = {
                    'passenger_count': 1,
                    'is_multi_passenger': False,
                    'selected_seats': [{
                        'seat': selected_seat,
                        'type': seat['type'],
                        'class': seat['class'],
                        'display_class': seat_class,
                        'price': context['seat_price'],
                    }],
                }
            else:
                messages.warning(request, "Please select seats first")
                return redirect('seat-selection', pk=pk)
        else:
            logger.debug("Session data mismatch: expected flight %s, got %s", pk, selected_flight)
            messages.warning(request, "Please select seats first")
            return redirect('seat-selection', pk=pk)
            
        try:
            return render(request, 'reservation.html', context)
        except Exception as template_error:
            logger.exception("Template rendering error")
            messages.error(request, "Unable to display the reservation form.")
            return redirect('user-dashboard')
            
    except models.Flights.DoesNotExist:
        messages.error(request, "Flight not found")
        return redirect('public-page')
    except Exception as e:
        logger.exception("Unable to display reservation form")
        messages.error(request, "Unable to display the reservation form.")
        return redirect('public-page')


@login_required
def home(request):
    context = context_data()
    context['page'] = 'home'
    context['page_title'] = 'Home'
    context['airlines'] = models.Airlines.objects.filter(delete_flag=0, status=1).count()
    context['airport'] = models.Airport.objects.filter(delete_flag=0, status=1).count()
    context['aircraft'] = models.Aircraft.objects.filter(status='1').count()
    context['flight'] = models.Flights.objects.filter(
        delete_flag=0,
        departure__gte=timezone.now(),
    ).count()
    context['pending_reservations'] = models.Reservation.objects.filter(status='0').count()
    context['confirmed_reservations'] = models.Reservation.objects.filter(status='1').count()
    return render(request, 'home.html', context)

def travel_chat(request):
    context = context_data()
    context['page_title'] = "AI Travel Assistant"
    context['page'] = 'travel-chat'
    return render(request, 'travel_chat.html', context)


def travel_chat_api(request):
    """
    AI Travel Assistant API for ARMS.

    Receives a user's travel question and returns:
    - AI/fallback travel response
    - Extracted travel preferences
    - Real available flights from the ARMS database
    """

    # ---------------------------------------------------------
    # 1. Allow only POST requests
    # ---------------------------------------------------------
    if request.method != 'POST':
        return HttpResponse(
            json.dumps({
                'status': 'failed',
                'message': 'Only POST requests are allowed.'
            }),
            content_type='application/json',
            status=405
        )

    # ---------------------------------------------------------
    # 2. Get user's message
    # ---------------------------------------------------------
    message = request.POST.get('message', '').strip()

    if not message:
        return HttpResponse(
            json.dumps({
                'status': 'failed',
                'message': 'Please type a travel question first.'
            }),
            content_type='application/json',
            status=400
        )

    # ---------------------------------------------------------
    # 3. Extract travel preferences
    # ---------------------------------------------------------
    try:
        prefs = extract_travel_preferences(message)
    except Exception as e:
        return HttpResponse(
            json.dumps({
                'status': 'failed',
                'message': 'Unable to understand your travel preferences.',
                'error': str(e)
            }),
            content_type='application/json',
            status=500
        )

    # ---------------------------------------------------------
    # 5. Search REAL flights from ARMS database
    # ---------------------------------------------------------
    try:
        flights = search_real_flights(prefs)
    except Exception as e:
        flights = []

    # ---------------------------------------------------------
    # 6. Generate a plan grounded in matching flight inventory
    # ---------------------------------------------------------
    try:
        response = get_travel_response(message, flights)
    except Exception as e:
        response = (
            "I could not generate the full travel plan right now. "
            "Please try again, or search the flight inventory directly."
        )

    # ---------------------------------------------------------
    # 7. Build response
    # ---------------------------------------------------------
    result = {
        'status': 'success',

        'response': response,

        'preferences': prefs,

        'flights': flights,

        'flight_count': len(flights),
    }

    # ---------------------------------------------------------
    # 8. Return JSON
    # ---------------------------------------------------------
    return HttpResponse(
        json.dumps(result, default=str),
        content_type='application/json',
        status=200
    )

def logout_user(request):
    # Clear all session data and log out the user
    request.session.flush()
    logout(request)
    messages.success(request, "You have been logged out successfully")
    return redirect('public-page')
    
@login_required
def profile(request):
    context = context_data()
    context['page'] = 'profile'
    context['page_title'] = "Profile"
    
    # Get user profile data if it exists
    try:
        context['user_profile'] = request.user.profile
    except:
        pass
        
    return render(request,'profile.html', context)

#Airline
@login_required
def list_airline(request):
    context = context_data()
    context['page_title'] ="Airlines"
    context['airlines'] = models.Airlines.objects.filter(delete_flag = 0).all()
    return render(request, 'airlines.html', context) 

@login_required
def manage_airline(request, pk = None):
    if pk is None:
        airline = {}
    else:
        airline = models.Airlines.objects.get(id = pk)
    context = context_data()
    context['page_title'] ="Manage Airline"
    context['airline'] = airline
    return render(request, 'manage_airline.html', context) 

@login_required
def save_airline(request):
    resp = { 'status': 'failed', 'msg':'' }
    if not request.method == 'POST':
       resp['msg'] = "No data has been sent."
    else:
        post = request.POST
        if not post['id'] == '':
            airline = models.Airlines.objects.get(id = post['id'])
            form = forms.SaveAirlines(request.POST, request.FILES, instance = airline)
        else:
            form = forms.SaveAirlines(request.POST, request.FILES)

        if form.is_valid():
            form.save()
            resp['status'] = 'success'
            if post['id'] == '':
                resp['msg'] = "New Airline has been added successfully."
            else:
                resp['msg'] = "Airline Details has been updated successfully."
            messages.success(request,f"{resp['msg']}")
        else:
            for field in form:
                for error in field.errors:
                    if not resp['msg'] == '':
                        resp['msg'] += "; "

                    resp['msg'] += str(f"[{field.name}] {error}")
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def delete_airline(request, pk=None):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'A POST request is required.'},
            status=405,
        )
    if pk is None:
        return JsonResponse(
            {'status': 'failed', 'msg': 'No ID has been sent.'},
            status=400,
        )

    updated = models.Airlines.objects.filter(pk=pk, delete_flag=0).update(
        delete_flag=1
    )
    if not updated:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Airline not found.'},
            status=404,
        )
    messages.success(request, "Airline has been archived successfully.")
    return JsonResponse({'status': 'success', 'msg': 'Airline archived.'})

    
#Airport
@login_required
def list_airport(request):
    context = context_data()
    context['page_title'] ="Airports"
    context['airports'] = models.Airport.objects.filter(delete_flag = 0).all()
    return render(request, 'airports.html', context) 

@login_required
def manage_airport(request, pk = None):
    if pk is None:
        airport = {}
    else:
        airport = models.Airport.objects.get(id = pk)
    context = context_data()
    context['page_title'] ="Manage Airport"
    context['airport'] = airport
    return render(request, 'manage_airport.html', context) 

@login_required
def save_airport(request):
    resp = { 'status': 'failed', 'msg':'' }
    if not request.method == 'POST':
       resp['msg'] = "No data has been sent."
    else:
        post = request.POST
        if not post['id'] == '':
            airport = models.Airport.objects.get(id = post['id'])
            form = forms.SaveAirports(request.POST, instance = airport)
        else:
            form = forms.SaveAirports(request.POST)

        if form.is_valid():
            form.save()
            resp['status'] = 'success'
            if post['id'] == '':
                resp['msg'] = "New Airport has been added successfully."
            else:
                resp['msg'] = "Airport Details has been updated successfully."
            messages.success(request,f"{resp['msg']}")
        else:
            for field in form:
                for error in field.errors:
                    if not resp['msg'] == '':
                        resp['msg'] += "; "

                    resp['msg'] += str(f"[{field.name}] {error}")
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def delete_airport(request, pk=None):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'A POST request is required.'},
            status=405,
        )
    if pk is None:
        return JsonResponse(
            {'status': 'failed', 'msg': 'No ID has been sent.'},
            status=400,
        )

    updated = models.Airport.objects.filter(pk=pk, delete_flag=0).update(
        delete_flag=1
    )
    if not updated:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Airport not found.'},
            status=404,
        )
    messages.success(request, "Airport has been archived successfully.")
    return JsonResponse({'status': 'success', 'msg': 'Airport archived.'})

#Flight
@login_required
def list_flight(request):
    context = context_data()
    context['page_title'] ="Flights"
    context['flights'] = models.Flights.objects.filter(delete_flag = 0).all()
    return render(request, 'flights.html', context) 

@login_required
def manage_flight(request, pk = None):
    if pk is None:
        flight = {}
    else:
        flight = models.Flights.objects.get(id = pk)
    airlines = models.Airlines.objects.filter(delete_flag = 0, status = 1).all()
    airports = models.Airport.objects.filter(delete_flag = 0, status = 1).all()
    aircraft_list = models.Aircraft.objects.filter(delete_flag = 0, status = 1).all()
    context = context_data()
    context['page_title'] ="Manage Flight"
    context['flight'] = flight
    context['airlines'] = airlines
    context['airports'] = airports
    context['aircraft_list'] = aircraft_list
    return render(request, 'manage_flight.html', context) 

@login_required
def save_flight(request):
    resp = { 'status': 'failed', 'msg':'' }
    if not request.method == 'POST':
       resp['msg'] = "No data has been sent."
    else:
        post = request.POST
        if not post['id'] == '':
            Flight = models.Flights.objects.get(id = post['id'])
            form = forms.SaveFlights(request.POST, instance = Flight)
        else:
            form = forms.SaveFlights(request.POST)

        if form.is_valid():
            flight = form.save(commit=False)
            # Get the aircraft data to update slots
            if post.get('aircraft'):
                try:
                    aircraft = models.Aircraft.objects.get(id=post.get('aircraft'))
                    flight.business_class_slots = aircraft.business_capacity
                    flight.economy_slots = aircraft.economy_capacity
                except Exception as e:
                    logger.exception("Error getting aircraft")
            
            flight.save()
            resp['status'] = 'success'
            if post['id'] == '':
                resp['msg'] = "New Flight has been added successfully."
            else:
                resp['msg'] = "Flight Details has been updated successfully."
            messages.success(request,f"{resp['msg']}")
        else:
            for field in form:
                for error in field.errors:
                    if not resp['msg'] == '':
                        resp['msg'] += "; "

                    resp['msg'] += str(f"[{field.name}] {error}")
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def view_flight(request, pk = None):
    if pk is None:
        flight = {}
    else:
        flight = models.Flights.objects.get(id = pk)
    context = context_data()
    context['page_title'] ="Flight Details"
    context['flight'] = flight
    return render(request, 'view_flight_details.html', context) 

@login_required
def delete_flight(request, pk=None):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'A POST request is required.'},
            status=405,
        )
    if pk is None:
        return JsonResponse(
            {'status': 'failed', 'msg': 'No ID has been sent.'},
            status=400,
        )

    updated = models.Flights.objects.filter(pk=pk, delete_flag=0).update(
        delete_flag=1
    )
    if not updated:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Flight not found.'},
            status=404,
        )
    messages.success(request, "Flight has been archived successfully.")
    return JsonResponse({'status': 'success', 'msg': 'Flight archived.'})

#Reservation
@login_required
def list_reservation(request):
    context = context_data()
    context['page_title'] ="Reservations"
    context['reservations'] = models.Reservation.objects.all()
    return render(request, 'reservation_list.html', context) 

@login_required
def view_reservation(request, pk = None):
    if pk is None:
        reservation = {}
    else:
        reservation = models.Reservation.objects.get(id = pk)
    context = context_data()
    context['page_title'] ="Reservation Details"
    context['reservation'] = reservation
    return render(request, 'view_reservation_details.html', context) 

@login_required
def delete_reservation(request, pk=None):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'A POST request is required.'},
            status=405,
        )
    if pk is None:
        return JsonResponse(
            {'status': 'failed', 'msg': 'No ID has been sent.'},
            status=400,
        )

    deleted_count, _ = models.Reservation.objects.filter(pk=pk).delete()
    if not deleted_count:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Reservation not found.'},
            status=404,
        )
    messages.success(request, "Reservation has been deleted successfully.")
    return JsonResponse({'status': 'success', 'msg': 'Reservation deleted.'})

@login_required
def update_reservation(request):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'A POST request is required.'},
            status=405,
        )

    reservation_id = request.POST.get('id')
    new_status = request.POST.get('status')
    if not reservation_id or new_status not in {'1', '2'}:
        return JsonResponse(
            {'status': 'failed', 'msg': 'A valid reservation and status are required.'},
            status=400,
        )

    try:
        with transaction.atomic():
            reservation = models.Reservation.objects.select_for_update().get(
                pk=reservation_id
            )
            if new_status == '1':
                updated = reservation.approve_reservation()
            elif reservation.status in {'0', '1'}:
                reservation.status = '2'
                reservation.save(update_fields=['status'])
                updated = True
            else:
                updated = False
    except models.Reservation.DoesNotExist:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Reservation not found.'},
            status=404,
        )

    if not updated:
        return JsonResponse(
            {'status': 'failed', 'msg': 'This reservation can no longer be updated.'},
            status=409,
        )

    messages.success(request, "Reservation Status has been updated successfully")
    return JsonResponse({'status': 'success', 'msg': 'Reservation updated.'})

@login_required
def aircraft(request):
    context = context_data()
    context['page'] = 'aircraft'
    context['page_title'] = "Aircraft List"
    context['aircraft_list'] = models.Aircraft.objects.filter(delete_flag=0)
    return render(request, 'aircraft.html', context)

@login_required
def manage_aircraft(request, pk=None):
    context = context_data()
    context['page'] = 'manage_aircraft'
    context['page_title'] = 'Manage Aircraft'
    if pk is None:
        context['aircraft'] = {}
    else:
        context['aircraft'] = models.Aircraft.objects.get(id=pk)
    return render(request, 'manage_aircraft.html', context)

@login_required
def save_aircraft(request):
    resp = {'status': 'failed', 'msg': ''}
    if request.method != 'POST':
        resp['msg'] = 'No data has been sent.'
    else:
        post = request.POST
        if not post.get('id') == '':
            # Editing
            try:
                aircraft = models.Aircraft.objects.get(id=post['id'])
                aircraft.code = post['code']
                aircraft.model = post['model']
                aircraft.manufacturer = post['manufacturer']
                aircraft.business_capacity = post['business_capacity']
                aircraft.economy_capacity = post['economy_capacity']
                aircraft.status = post['status']
                aircraft.save()
                resp['status'] = 'success'
                messages.success(request, "Aircraft has been updated successfully.")
            except Exception as e:
                resp['msg'] = f"Error updating aircraft: {str(e)}"
        else:
            # Adding new
            try:
                # Check if aircraft with same code already exists
                if models.Aircraft.objects.filter(code=post['code']).exists():
                    resp['msg'] = f"Aircraft with code {post['code']} already exists."
                else:
                    aircraft = models.Aircraft(
                        code=post['code'],
                        model=post['model'],
                        manufacturer=post['manufacturer'],
                        business_capacity=post['business_capacity'],
                        economy_capacity=post['economy_capacity'],
                        status=post['status']
                    )
                    aircraft.save()
                    resp['status'] = 'success'
                    messages.success(request, "Aircraft has been added successfully.")
            except Exception as e:
                resp['msg'] = f"Error adding aircraft: {str(e)}"
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def delete_aircraft(request, pk=None):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'A POST request is required.'},
            status=405,
        )
    if pk is None:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Aircraft ID is not provided.'},
            status=400,
        )

    updated = models.Aircraft.objects.filter(
        pk=pk,
        delete_flag=0,
    ).update(delete_flag=1)
    if not updated:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Aircraft not found.'},
            status=404,
        )

    messages.success(request, "Aircraft has been archived successfully.")
    return JsonResponse(
        {'status': 'success', 'msg': 'Aircraft has been archived successfully.'}
    )


def get_captcha(request):
    """
    AJAX view to get CAPTCHA HTML - Simple Math Version for Reliability
    """
    import random
    
    # Generate simple math captcha (more reliable than django-simple-captcha)
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    answer = num1 + num2
    
    request.session['simple_captcha'] = str(answer)
    
    captcha_html = f'''
    <input type="hidden" name="captcha_0" value="simple_math" id="id_captcha_0">
    <div class="input-group">
        <div class="input-group-text bg-light">
            <strong>{num1} + {num2} = ?</strong>
        </div>
        <input type="text" name="captcha_1" id="id_captcha_1" class="form-control" placeholder="Enter answer" required>
        <button type="button" class="btn btn-outline-secondary" onclick="refreshCaptcha()">
            <i class="fas fa-sync-alt"></i>
        </button>
    </div>
    <small class="text-muted">Solve the math problem to verify you're human</small>
    '''
    
    return HttpResponse(captcha_html)


def _reservation_verification_failure(request, message):
    now = int(timezone.now().timestamp())
    window_started = request.session.get('reservation_verify_window', now)
    if not isinstance(window_started, int) or now - window_started >= 900:
        window_started = now
        request.session['reservation_verify_attempts'] = 0
    current_attempts = request.session.get('reservation_verify_attempts', 0)
    if not isinstance(current_attempts, int):
        current_attempts = 0
    attempts = current_attempts + 1
    request.session['reservation_verify_window'] = window_started
    request.session['reservation_verify_attempts'] = attempts
    if attempts >= 5:
        return JsonResponse(
            {'status': 'failed', 'msg': 'Too many attempts. Please wait before trying again.'},
            status=429,
        )
    return JsonResponse({'status': 'failed', 'msg': message}, status=400)


def verify_reservation(request):
    """
    Verify user password and CAPTCHA before allowing reservation submission
    """
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'failed', 'msg': 'Invalid request method.'},
            status=405,
        )
    
    if not request.user.is_authenticated:
        return JsonResponse(
            {'status': 'failed', 'msg': 'You must be logged in to make a reservation.'},
            status=401,
        )

    request.session.pop('reservation_verified_until', None)
    attempts = request.session.get('reservation_verify_attempts', 0)
    if isinstance(attempts, int) and attempts >= 5:
        window_started = request.session.get('reservation_verify_window', 0)
        if (
            isinstance(window_started, (int, float))
            and timezone.now().timestamp() - window_started < 900
        ):
            return JsonResponse(
                {'status': 'failed', 'msg': 'Too many attempts. Please wait before trying again.'},
                status=429,
            )
        request.session.pop('reservation_verify_attempts', None)
        request.session.pop('reservation_verify_window', None)
    
    # Verify password
    password = request.POST.get('password')
    if not password:
        return _reservation_verification_failure(request, 'Password is required.')

    if not request.user.check_password(password):
        return _reservation_verification_failure(
            request,
            'Incorrect password. Please try again.',
        )
    
    # Verify CAPTCHA
    captcha_key = request.POST.get('captcha_0')
    captcha_value = request.POST.get('captcha_1')
    
    if not captcha_key or not captcha_value:
        return _reservation_verification_failure(
            request,
            'Please complete the security check.',
        )
    
    # Handle different CAPTCHA types
    if captcha_key == 'simple_math':
        # Simple math CAPTCHA verification
        correct_answer = request.session.get('simple_captcha')
        if not correct_answer or not constant_time_compare(captcha_value, correct_answer):
            return _reservation_verification_failure(
                request,
                'Incorrect answer. Please try again.',
            )
        request.session.pop('simple_captcha', None)
    else:
        try:
            from captcha.models import CaptchaStore
        except ImportError:
            logger.exception("CAPTCHA package is unavailable")
            return JsonResponse(
                {'status': 'failed', 'msg': 'Security verification is temporarily unavailable.'},
                status=503,
            )
        try:
            captcha = CaptchaStore.objects.get(hashkey=captcha_key)
            if not constant_time_compare(
                captcha.response.casefold(),
                captcha_value.casefold(),
            ):
                return _reservation_verification_failure(
                    request,
                    'Security check failed. Please try again.',
                )
            captcha.delete()
        except CaptchaStore.DoesNotExist:
            return _reservation_verification_failure(
                request,
                'Invalid security check. Please refresh and try again.',
            )
        except Exception:
            logger.exception("CAPTCHA verification failed")
            return JsonResponse(
                {'status': 'failed', 'msg': 'Security verification is temporarily unavailable.'},
                status=503,
            )

    request.session['reservation_verified_until'] = (
        timezone.now().timestamp() + 180
    )
    request.session.pop('reservation_verify_attempts', None)
    request.session.pop('reservation_verify_window', None)
    return JsonResponse({'status': 'success', 'msg': 'Verification successful.'})


def mark_notification_read(request):
    """
    Mark a notification as read and return full content
    """
    resp = {'status': 'failed', 'msg': ''}
    
    if not request.method == 'POST':
        resp['msg'] = 'Invalid request method.'
        return HttpResponse(json.dumps(resp), content_type="application/json")
    
    if not request.user.is_authenticated:
        resp['msg'] = 'You must be logged in.'
        return HttpResponse(json.dumps(resp), content_type="application/json")
    
    notification_id = request.POST.get('id')
    if not notification_id:
        resp['msg'] = 'Notification ID is required.'
        return HttpResponse(json.dumps(resp), content_type="application/json")
    
    try:
        from armsApp.models import UserNotification
        notification = UserNotification.objects.get(id=notification_id, user=request.user)
        notification.is_read = True
        notification.save()
        
        resp['status'] = 'success'
        resp['full_message'] = notification.message
        resp['title'] = notification.title
        
    except UserNotification.DoesNotExist:
        resp['msg'] = 'Notification not found.'
    except Exception as e:
        resp['msg'] = f'Error: {str(e)}'
    
    return HttpResponse(json.dumps(resp), content_type="application/json")
