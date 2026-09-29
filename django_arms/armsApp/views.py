403
import datetime
import os
import requests
from django.shortcuts import redirect, render
import json
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from armsApp import models, forms
from django.http import HttpResponse
from django.db.models import Q, Min, Max
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction

import json

from django.http import HttpResponse
from django.shortcuts import render, redirect


from armsApp.utils import context_data
from armsApp.ai_chatbot import (
    get_travel_response,
    extract_travel_preferences,
    search_real_flights,
)
import logging

logger = logging.getLogger(__name__)
    
@login_required
def update_reservation(request):
    resp = { 'status' : 'failed', 'msg' : '' }
    if not request.method == 'POST':
        resp['msg'] = 'No data has been sent'
    else:
        try:
            models.Reservation.objects.filter(id = request.POST['id']).update(status=request.POST['status'])
            resp['status'] = 'success'
            messages.success(request, "Reservation Status has been updated successfully")
        except:
            resp['msg'] = 'Reservation Status has failed to update'
    return HttpResponse(json.dumps(resp), content_type="application/json")

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
    resp = {"status": "failed", "msg": ""}
    if not request.method == 'POST':
        resp['msg'] = "No data has been sent."
    else:
        reservation_id = request.POST.get('id')
        try:
            reservation = models.Reservation.objects.get(id=reservation_id, user=request.user)
            
            # Check if flight has already departed
            from django.utils import timezone
            current_time = timezone.now()
            
            if reservation.flight.departure <= current_time:
                resp['msg'] = "Cannot cancel reservation. The flight has already departed."
                return HttpResponse(json.dumps(resp), content_type="application/json")
            
            # Check if reservation is already cancelled
            if reservation.status == '2':
                resp['msg'] = "This reservation has already been cancelled."
                return HttpResponse(json.dumps(resp), content_type="application/json")
            
            reservation.status = '2'  # Cancelled
            reservation.save()
            resp['status'] = 'success'
            resp['msg'] = "Reservation successfully cancelled."
        except models.Reservation.DoesNotExist:
            resp['msg'] = "Reservation not found or you don't have permission to cancel it."
        except Exception as e:
            resp['msg'] = f"Error: {str(e)}"
    
    return HttpResponse(json.dumps(resp), content_type="application/json")

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
        
        # Generate seat maps - this is a simplification
        # In a real application, you'd check the database for taken seats
        
        # Business class seats (2-2 configuration: A,B | C,D)
        business_seats = []
        business_rows = (flight.business_class_slots + 3) // 4  # Calculate number of rows needed
        
        seat_letters = ['A', 'B', 'C', 'D']
        for row in range(1, business_rows + 1):
            for seat_letter in seat_letters:
                seat_code = f"B{row}{seat_letter}"
                
                # Check if this seat is already reserved
                is_reserved = models.Reservation.objects.filter(
                    flight=flight,
                    type='1',  # Business
                    seat_number=seat_code,
                    status__in=['0', '1']  # Pending or Confirmed
                ).exists()
                
                business_seats.append({
                    'seat': seat_code,
                    'available': not is_reserved
                })
    except models.Flights.DoesNotExist:
        messages.error(request, "Flight not found")
        return redirect('public-page')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('public-page')
    
    # Economy seats (3-3 configuration: A,B,C | D,E,F)
    economy_seats = []
    economy_rows = (flight.economy_slots + 5) // 6  # Calculate number of rows needed
    
    seat_letters = ['A', 'B', 'C', 'D', 'E', 'F']
    for row in range(1, economy_rows + 1):
        for seat_letter in seat_letters:
            seat_code = f"E{row}{seat_letter}"
            
            # Check if this seat is already reserved
            is_reserved = models.Reservation.objects.filter(
                flight=flight,
                type='2',  # Economy
                seat_number=seat_code,
                status__in=['0', '1']  # Pending or Confirmed
            ).exists()
            
            economy_seats.append({
                'seat': seat_code,
                'available': not is_reserved
            })
    
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
            
            # Parse the JSON data
            try:
                seats_info = json.loads(selected_seats_data)
                selected_seats = seats_info.get('seats', [])
                passenger_count = seats_info.get('passenger_count', 1)
            except json.JSONDecodeError:
                messages.error(request, "Invalid seat selection data. Please try again.")
                return render(request, 'seat_selection.html', context)
            
            if not selected_seats or len(selected_seats) == 0:
                messages.error(request, "Please select at least one seat")
                return render(request, 'seat_selection.html', context)
            
            if len(selected_seats) != passenger_count:
                messages.error(request, f"Please select exactly {passenger_count} seats")
                return render(request, 'seat_selection.html', context)
            
            # Verify all seats are still available
            unavailable_seats = []
            for seat_info in selected_seats:
                seat_number = seat_info.get('seat')
                seat_class = seat_info.get('class')
                
                # Determine the type code based on class
                type_code = '1' if seat_class == 'business' else '2'
                
                # Check if seat is available
                is_reserved = models.Reservation.objects.filter(
                    flight=flight,
                    seat_number=seat_number,
                    status__in=['0', '1']  # Pending or Confirmed
                ).exists()
                
                if is_reserved:
                    unavailable_seats.append(seat_number)
            
            if unavailable_seats:
                messages.error(request, f"Sorry, the following seats are no longer available: {', '.join(unavailable_seats)}. Please select different seats.")
                return render(request, 'seat_selection.html', context)
            
            # Store multi-seat data in session for the next step
            request.session['selected_flight'] = str(pk)
            request.session['selected_seats_data'] = selected_seats_data
            request.session['passenger_count'] = passenger_count
            
            try:
                # Redirect to reservation form
                return redirect('reserve-form', pk=pk)
            except Exception as e:
                logger.exception("Redirect error during seat selection")
                messages.error(request, f"Error during redirect: {str(e)}")
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
                        security_answer=form.cleaned_data['security_answer'],
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
            
            resp['msg'] = "<br>".join(error_messages)
            if not resp['msg']:
                resp['msg'] = "Form validation failed. Please check all fields and try again."
    except Exception:
        logger.exception("Unexpected error in save_register")
        resp['msg'] = "An unexpected error occurred. Please try again."
    
    # Ensure the return statement is always executed
    return HttpResponse(json.dumps(resp), content_type="application/json")
            
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
    resp = {"status":'failed','msg':'', 'redirect': ''}
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
                login(request, user)
                resp['status'] = 'success'
                
                # Direct redirect based on user type
                try:
                    profile = UserProfile.objects.get(user=user)
                    if profile.user_type == 'admin':
                        resp['redirect'] = '/home'  # Admin dashboard
                    else:
                        resp['redirect'] = '/user_dashboard'  # Regular user dashboard
                except:
                    # If no profile exists yet, redirect to user dashboard
                    resp['redirect'] = '/user_dashboard'
            else:
                resp['msg'] = "Account is inactive"
        else:
            resp['msg'] = "Incorrect User ID or password"
    return HttpResponse(json.dumps(resp),content_type='application/json')

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
    resp = { 'status': 'failed', 'msg':'' }
    if not request.method == 'POST':
        resp['msg'] = "No data has been sent."
    else:
        # Check if this is a multi-passenger reservation
        passenger_count = int(request.POST.get('passenger_count', 1))
        
        if passenger_count > 1:
            # Handle multi-passenger reservation
            try:
                from django.utils import timezone
                current_time = timezone.now()
                
                # Get flight details from the form
                flight_id = request.POST.get('flight')
                flight = models.Flights.objects.get(id=flight_id)
                
                if flight.departure <= current_time:
                    resp['msg'] = "Sorry, this flight has already departed. You cannot make a reservation for a past flight."
                    return HttpResponse(json.dumps(resp), content_type="application/json")
                
                # Collect all passenger data and validate seats
                passengers_data = []
                reserved_seats = []
                
                for i in range(passenger_count):
                    # Get passenger information
                    passenger_data = {
                        'first_name': request.POST.get(f'passenger_{i}_first_name'),
                        'middle_name': request.POST.get(f'passenger_{i}_middle_name', ''),
                        'last_name': request.POST.get(f'passenger_{i}_last_name'),
                        'gender': request.POST.get(f'passenger_{i}_gender'),
                        'age': request.POST.get(f'passenger_{i}_age', ''),
                        'seat': request.POST.get(f'passenger_{i}_seat'),
                        'type': request.POST.get(f'passenger_{i}_type', '2')
                    }
                    
                    # Validate required fields
                    if not all([passenger_data['first_name'], passenger_data['last_name'], 
                               passenger_data['gender'], passenger_data['seat']]):
                        resp['msg'] = f"Please complete all required information for Passenger {i+1}"
                        return HttpResponse(json.dumps(resp), content_type="application/json")
                    
                    # Check if seat is available
                    is_reserved = models.Reservation.objects.filter(
                        flight=flight,
                        seat_number=passenger_data['seat'],
                        status__in=['0', '1']  # Pending or Confirmed
                    ).exists()
                    
                    if is_reserved or passenger_data['seat'] in reserved_seats:
                        resp['msg'] = f"Sorry, seat {passenger_data['seat']} is no longer available. Please go back and select different seats."
                        return HttpResponse(json.dumps(resp), content_type="application/json")
                    
                    reserved_seats.append(passenger_data['seat'])
                    passengers_data.append(passenger_data)
                
                # Get shared contact information
                contact_info = {
                    'email': request.POST.get('email'),
                    'contact': request.POST.get('contact'),
                    'address': request.POST.get('address', '')
                }
                
                # Create reservations for all passengers
                created_reservations = []
                for i, passenger in enumerate(passengers_data):
                    reservation = models.Reservation(
                        flight=flight,
                        first_name=passenger['first_name'],
                        middle_name=passenger['middle_name'] or '',
                        last_name=passenger['last_name'],
                        gender=passenger['gender'],
                        email=contact_info['email'],
                        contact=contact_info['contact'],
                        address=contact_info['address'],
                        seat_number=passenger['seat'],
                        type=passenger['type'],
                        status='0'  # Pending Admin Approval
                    )
                    
                    # Link to user if authenticated
                    if request.user.is_authenticated:
                        reservation.user = request.user
                    
                    reservation.save()
                    created_reservations.append(reservation)
                
                # Clear session data
                session_keys_to_clear = [
                    'selected_seat', 'selected_type', 'selected_flight', 
                    'selected_seats_data', 'passenger_count'
                ]
                for key in session_keys_to_clear:
                    if key in request.session:
                        del request.session[key]
                
                resp['status'] = 'success'
                resp['msg'] = f"Your group reservation for {passenger_count} passengers has been submitted successfully! All bookings are now pending admin approval. You will be notified once the admin reviews your reservations. Thank you!"
                messages.success(request, resp['msg'])
                
            except Exception as e:
                resp['msg'] = f"An error occurred while processing your group reservation: {str(e)}"
        
        else:
            # Handle single passenger reservation (original code)
            form = forms.SaveReservation(request.POST)
            if form.is_valid():
                try:
                    reservation = form.save(commit=False)
                    
                    # Check if flight has already departed
                    from django.utils import timezone
                    current_time = timezone.now()
                    
                    if reservation.flight.departure <= current_time:
                        resp['msg'] = "Sorry, this flight has already departed. You cannot make a reservation for a past flight."
                        return HttpResponse(json.dumps(resp), content_type="application/json")
                    
                    # Link reservation to current user if authenticated
                    if request.user.is_authenticated:
                        reservation.user = request.user
                    
                    # Add seat number from form data or session
                    if 'seat_number' in request.POST and request.POST['seat_number']:
                        reservation.seat_number = request.POST['seat_number']
                        if 'type' in request.POST and request.POST['type']:
                            reservation.type = request.POST['type']
                    elif 'selected_seat' in request.session:
                        reservation.seat_number = request.session.get('selected_seat')
                        reservation.type = request.session.get('selected_type', '2')  # Default to economy if not set
                    
                    # Check if seat is still available
                    is_reserved = models.Reservation.objects.filter(
                        flight=reservation.flight,
                        type=reservation.type,
                        seat_number=reservation.seat_number,
                        status__in=['0', '1']  # Pending or Confirmed
                    ).exists()
                    
                    if is_reserved:
                        resp['msg'] = "Sorry, this seat has been taken. Please go back and select another seat."
                        return HttpResponse(json.dumps(resp), content_type="application/json")
                    
                    # Set reservation status to pending admin approval
                    reservation.status = '0'  # Pending Admin Approval
                    
                    # Save the reservation
                    reservation.save()
                    
                    # Clear the session data after successful save
                    session_keys_to_clear = [
                        'selected_seat', 'selected_type', 'selected_flight',
                        'selected_seats_data', 'passenger_count'
                    ]
                    for key in session_keys_to_clear:
                        if key in request.session:
                            del request.session[key]
                        
                    resp['status'] = 'success'
                    resp['msg'] = "Your reservation has been submitted successfully! It is now pending admin approval. You will be notified once the admin reviews your booking. Thank you!"
                    messages.success(request, f"{resp['msg']}")
                    
                except Exception as e:
                    resp['msg'] = f"An error occurred: {str(e)}"
            else:
                for field in form:
                    for error in field.errors:
                        if not resp['msg'] == '':
                            resp['msg'] += str("<br />")

                        resp['msg'] += str(f"[{field.name}] {error}")
    return HttpResponse(json.dumps(resp), content_type="application/json")

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
        
        # Check if we have seat selection in the session
        selected_seats_data = request.session.get('selected_seats_data')
        passenger_count = request.session.get('passenger_count', 1)
        selected_flight = request.session.get('selected_flight')
        
        # Legacy support for single seat selection
        selected_seat = request.session.get('selected_seat')
        selected_type = request.session.get('selected_type')
        
        # Validate that the seat selection matches the current flight
        if selected_flight and str(selected_flight) == str(pk):
            # Check for multi-seat selection first
            if selected_seats_data and passenger_count:
                try:
                    import json
                    seats_info = json.loads(selected_seats_data)
                    selected_seats = seats_info.get('seats', [])
                    
                    if selected_seats and len(selected_seats) == passenger_count:
                        # Multi-passenger reservation
                        context['selected_seats'] = selected_seats
                        context['passenger_count'] = passenger_count
                        context['is_multi_passenger'] = True
                        
                        # Calculate total price for all seats
                        total_price = 0
                        seat_details = []
                        
                        for seat_info in selected_seats:
                            seat_class = seat_info.get('class')
                            if seat_class == 'business':
                                seat_price = flight.business_class_price
                                class_name = "Business Class"
                            else:
                                seat_price = flight.economy_price
                                class_name = "Economy"
                            
                            total_price += seat_price
                            seat_details.append({
                                'seat': seat_info.get('seat'),
                                'class': class_name,
                                'price': seat_price
                            })
                        
                        context['seat_details'] = seat_details
                        context['total_price'] = total_price
                    else:
                        messages.error(request, "Invalid seat selection data. Please select seats again.")
                        return redirect('seat-selection', pk=pk)
                        
                except (json.JSONDecodeError, KeyError) as e:
                    logger.exception("Error parsing seat selection data")
                    messages.error(request, "Invalid seat selection data. Please select seats again.")
                    return redirect('seat-selection', pk=pk)
                    
            # Fallback to legacy single seat selection
            elif selected_seat and selected_type:
                context['selected_seat'] = selected_seat
                context['selected_type'] = selected_type
                context['passenger_count'] = 1
                context['is_multi_passenger'] = False
                seat_class = "Business Class" if selected_type == '1' else "Economy"
                context['seat_class'] = seat_class
                
                # Calculate price based on seat type
                if selected_type == '1':
                    context['seat_price'] = context['flight'].business_class_price
                else:
                    context['seat_price'] = context['flight'].economy_price
                    
                logger.debug("Single-passenger context prepared: seat=%s, class=%s, price=%s", selected_seat, seat_class, context.get('seat_price'))
            else:
                # No valid seat selection found
                messages.warning(request, "Please select seats first")
                return redirect('seat-selection', pk=pk)
        else:
            # If no seat selection or flight mismatch, redirect to seat selection
            logger.debug("Session data mismatch: expected flight %s, got %s", pk, selected_flight)
            messages.warning(request, "Please select seats first")
            return redirect('seat-selection', pk=pk)
            
        try:
            return render(request, 'reservation.html', context)
        except Exception as template_error:
            logger.exception("Template rendering error")
            messages.error(request, f"Error rendering reservation form: {str(template_error)}")
            return redirect('user-dashboard')
            
    except models.Flights.DoesNotExist:
        messages.error(request, "Flight not found")
        return redirect('public-page')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('public-page')


@login_required
def home(request):
    context = context_data()
    context['page'] = 'home'
    context['page_title'] = 'Home'
    context['airlines'] = models.Airlines.objects.filter(delete_flag=0, status = 1).count()
    context['airport'] = models.Airport.objects.filter(delete_flag=0, status = 1).count()
    now = datetime.datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")
    hour = now.strftime("%H")
    context['flight'] = models.Flights.objects.filter(delete_flag=0,
                            departure__year__gte = year,
                            departure__month__gte = month,
                            departure__day__gte = day,
                            departure__hour__gte = hour,
                            ).count()
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
    # 4. Generate AI travel response
    # ---------------------------------------------------------
    try:
        response = get_travel_response(message)
    except Exception as e:
        response = (
            "I could not generate the AI recommendation right now. "
            "However, I can still search the available flights for you."
        )

    # ---------------------------------------------------------
    # 5. Search REAL flights from ARMS database
    # ---------------------------------------------------------
    try:
        flights = search_real_flights(prefs)
    except Exception as e:
        flights = []

    # ---------------------------------------------------------
    # 6. Build response
    # ---------------------------------------------------------
    result = {
        'status': 'success',

        'response': response,

        'preferences': prefs,

        'flights': flights,

        'flight_count': len(flights),
    }

    # ---------------------------------------------------------
    # 7. Return JSON
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
                        resp['msg'] += str("<br />")

                    resp['msg'] += str(f"[{field.name}] {error}")
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def delete_airline(request, pk=None):
    resp = { 'status' : 'failed', 'msg' : '' }
    if pk is None:
        resp['msg'] = 'No ID has been sent'
    else:
        try:
            models.Airlines.objects.filter(id = pk).update(delete_flag = 1)
            resp['status'] = 'success'
            messages.success(request, "Airline has been deleted successfully")
        except:
            resp['msg'] = 'Airline has failed to delete'
    return HttpResponse(json.dumps(resp), content_type="application/json")

    
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
                        resp['msg'] += str("<br />")

                    resp['msg'] += str(f"[{field.name}] {error}")
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def delete_airport(request, pk=None):
    resp = { 'status' : 'failed', 'msg' : '' }
    if pk is None:
        resp['msg'] = 'No ID has been sent'
    else:
        try:
            models.Airport.objects.filter(id = pk).update(delete_flag = 1)
            resp['status'] = 'success'
            messages.success(request, "Airport has been deleted successfully")
        except:
            resp['msg'] = 'airport has failed to delete'
    return HttpResponse(json.dumps(resp), content_type="application/json")

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
                        resp['msg'] += str("<br />")

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
    resp = { 'status' : 'failed', 'msg' : '' }
    if pk is None:
        resp['msg'] = 'No ID has been sent'
    else:
        try:
            models.Flights.objects.filter(id = pk).update(delete_flag = 1)
            resp['status'] = 'success'
            messages.success(request, "Flight has been deleted successfully")
        except:
            resp['msg'] = 'Flight has failed to delete'
    return HttpResponse(json.dumps(resp), content_type="application/json")

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
    resp = { 'status' : 'failed', 'msg' : '' }
    if pk is None:
        resp['msg'] = 'No ID has been sent'
    else:
        try:
            models.Reservation.objects.filter(id = pk).delete()
            resp['status'] = 'success'
            messages.success(request, "Reservation has been deleted successfully")
        except:
            resp['msg'] = 'Reservation has failed to delete'
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def update_reservation(request):
    resp = { 'status' : 'failed', 'msg' : '' }
    if not request.method == 'POST':
        resp['msg'] = 'No ID has been sent'
    else:
        try:
            models.Reservation.objects.filter(id = request.POST['id']).update(status=request.POST['status'])
            resp['status'] = 'success'
            messages.success(request, "Reservation Status has been updated successfully")
        except:
            resp['msg'] = 'Reservation Status has failed to update'
    return HttpResponse(json.dumps(resp), content_type="application/json")

@login_required
def aircraft(request):
    context = context_data()
    context['page'] = 'aircraft'
    context['page_title'] = "Aircraft List"
    context['aircraft_list'] = models.Aircraft.objects.all()
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
    resp = {'status': 'failed', 'msg': ''}
    if pk is None:
        resp['msg'] = 'Aircraft ID is not provided.'
    else:
        try:
            models.Aircraft.objects.filter(id=pk).delete()
            resp['status'] = 'success'
            messages.success(request, "Aircraft has been deleted successfully.")
        except Exception as e:
            resp['msg'] = f"Error deleting aircraft: {str(e)}"
    return HttpResponse(json.dumps(resp), content_type="application/json")


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


def verify_reservation(request):
    """
    Verify user password and CAPTCHA before allowing reservation submission
    """
    resp = {'status': 'failed', 'msg': ''}
    
    if not request.method == 'POST':
        resp['msg'] = 'Invalid request method.'
        return HttpResponse(json.dumps(resp), content_type="application/json")
    
    if not request.user.is_authenticated:
        resp['msg'] = 'You must be logged in to make a reservation.'
        return HttpResponse(json.dumps(resp), content_type="application/json")
    
    # Verify password
    password = request.POST.get('password')
    if not password:
        resp['msg'] = 'Password is required.'
        return HttpResponse(json.dumps(resp), content_type="application/json")
    
    if not request.user.check_password(password):
        resp['msg'] = 'Incorrect password. Please try again.'
        return HttpResponse(json.dumps(resp), content_type="application/json")
    
    # Verify CAPTCHA
    captcha_key = request.POST.get('captcha_0')
    captcha_value = request.POST.get('captcha_1')
    
    if not captcha_key or not captcha_value:
        resp['msg'] = 'Please complete the security check.'
        return HttpResponse(json.dumps(resp), content_type="application/json")
    
    # Handle different CAPTCHA types
    if captcha_key == 'simple_math':
        # Simple math CAPTCHA verification
        correct_answer = request.session.get('simple_captcha')
        if not correct_answer or captcha_value != correct_answer:
            resp['msg'] = 'Incorrect answer. Please try again.'
            return HttpResponse(json.dumps(resp), content_type="application/json")
        # Clear the session
        if 'simple_captcha' in request.session:
            del request.session['simple_captcha']
    else:
        # Django CAPTCHA verification
        try:
            from captcha.models import CaptchaStore
            captcha = CaptchaStore.objects.get(hashkey=captcha_key)
            if captcha.response.lower() != captcha_value.lower():
                resp['msg'] = 'Security check failed. Please try again.'
                return HttpResponse(json.dumps(resp), content_type="application/json")
            # Remove used CAPTCHA
            captcha.delete()
        except CaptchaStore.DoesNotExist:
            resp['msg'] = 'Invalid security check. Please refresh and try again.'
            return HttpResponse(json.dumps(resp), content_type="application/json")
        except Exception as e:
            # Fallback to simple verification if CAPTCHA system fails
            resp['msg'] = 'Security check system error. Please try again.'
            return HttpResponse(json.dumps(resp), content_type="application/json")
    
    resp['status'] = 'success'
    resp['msg'] = 'Verification successful.'
    return HttpResponse(json.dumps(resp), content_type="application/json")


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
