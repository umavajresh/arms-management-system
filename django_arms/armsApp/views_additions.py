from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
import json
from armsApp import models
from armsApp.utils import context_data

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

def user_dashboard(request):
    context = context_data()
    context['page_title'] = "User Dashboard"
    
    # Get recent searches if implemented
    context['recent_searches'] = []
    
    # If the user has a profile, get reservations
    if request.user.is_authenticated:
        return render(request, 'user_dashboard.html', context)
    else:
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
            
            # Check if reservation can be cancelled
            if reservation.status == '2':
                resp['msg'] = "This reservation has already been cancelled."
                return HttpResponse(json.dumps(resp), content_type="application/json")
            elif reservation.status == '3':
                resp['msg'] = "This reservation has been rejected by the admin and cannot be cancelled."
                return HttpResponse(json.dumps(resp), content_type="application/json")
            
            # Only pending (0) and approved (1) reservations can be cancelled
            if reservation.status not in ['0', '1']:
                resp['msg'] = "This reservation cannot be cancelled."
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

def upcoming_flights(request):
    """
    Public view for upcoming flights that doesn't require admin login
    """
    context = context_data()
    context['page_title'] = "Upcoming Flights"
    
    # Get filter parameters
    days = int(request.GET.get('days', 3))  # Default to 3 days for public view
    airline_id = request.GET.get('airline')
    from_airport = request.GET.get('from_airport')
    to_airport = request.GET.get('to_airport')
    date_filter = request.GET.get('date')
    
    # Date range
    today = timezone.now().date()
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            end_date = filter_date + timedelta(days=days)
            start_date = filter_date
        except ValueError:
            end_date = today + timedelta(days=days)
            start_date = today
    else:
        end_date = today + timedelta(days=days)
        start_date = today
    
    # Base queryset - only show flights that haven't departed yet
    current_time = timezone.now()
    flights = models.Flights.objects.filter(
        departure__date__gte=start_date,
        departure__date__lte=end_date,
        departure__gte=current_time,  # Only future flights
        delete_flag=0  # Only active flights
    ).order_by('departure')
    
    # Apply filters
    if airline_id:
        flights = flights.filter(airline_id=airline_id)
    
    if from_airport:
        flights = flights.filter(from_airport__code__iexact=from_airport)
        
    if to_airport:
        flights = flights.filter(to_airport__code__iexact=to_airport)
    
    # Get filter options for dropdowns
    airlines = models.Airlines.objects.filter(status='1').order_by('name')
    airports = models.Airport.objects.filter(status='1').order_by('code')
    
    context['flights'] = flights
    context['today'] = today
    context['start_date'] = start_date
    context['end_date'] = end_date
    context['days'] = days
    context['days_options'] = [1, 3, 7, 14, 30]
    context['airlines'] = airlines
    context['airports'] = airports
    context['selected_airline'] = airline_id
    context['selected_from_airport'] = from_airport
    context['selected_to_airport'] = to_airport
    context['selected_date'] = date_filter if date_filter else today.strftime('%Y-%m-%d')
    
    return render(request, 'upcoming_flights.html', context)

def seat_selection(request, pk=None):
    context = context_data()
    context['page_title'] = "Select Your Seat"
    
    if pk is None:
        messages.error(request, "Invalid Flight ID")
        return redirect('public-page')
    
    flight = models.Flights.objects.get(id=pk)
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
        # Process the seat selection
        seat_number = request.POST.get('seat_number')
        seat_type = request.POST.get('type')
        
        # Store in session for the next step
        request.session['selected_flight'] = pk
        request.session['selected_seat'] = seat_number
        request.session['selected_type'] = seat_type
        
        # Redirect to reservation form
        return redirect('reserve-form', pk=pk)
    
    return render(request, 'seat_selection.html', context)
