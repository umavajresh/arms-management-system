from django.contrib import admin
from django.urls import path
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Count, Sum, Q
from datetime import timedelta, datetime
from armsApp.models import Flights, Airlines, Airport, Reservation, FlightSchedule, Aircraft
import logging

logger = logging.getLogger(__name__)

class UpcomingFlightsAdminView:
    """
    Admin view to display upcoming flights
    """
    
    def __init__(self, admin_site):
        self.admin_site = admin_site
    
    def get_urls(self):
        urls = [
            path('upcoming-flights/', self.admin_site.admin_view(self.upcoming_flights_view), name='upcoming-flights'),
        ]
        return urls
    
    def upcoming_flights_view(self, request):
        # Get filter parameters
        days = int(request.GET.get('days', 7))
        airline_id = request.GET.get('airline')
        airport_id = request.GET.get('airport')
        aircraft_id = request.GET.get('aircraft')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        status = request.GET.get('status')
        sort_by = request.GET.get('sort', 'departure')  # Default sort by departure
        
        # Date range
        today = timezone.now().date()
        
        # If custom date range is provided
        if date_from:
            try:
                today = datetime.strptime(date_from, '%Y-%m-%d').date()
            except ValueError:
                logger.debug("Invalid date_from provided: %s", date_from)
                
        if date_to:
            try:
                end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                logger.debug("Invalid date_to provided: %s", date_to)
                end_date = today + timedelta(days=days)
        else:
            end_date = today + timedelta(days=days)
        
        # Base queryset
        flights = Flights.objects.filter(
            departure__date__gte=today,
            departure__date__lte=end_date
        )
        
        # Apply filters
        if airline_id:
            flights = flights.filter(airline_id=airline_id)
        
        if airport_id:
            flights = flights.filter(
                Q(from_airport_id=airport_id) | Q(to_airport_id=airport_id)
            )
        
        if aircraft_id:
            flights = flights.filter(aircraft_id=aircraft_id)
            
        if status:
            flights = flights.filter(status=status)
        
        # Execute query to get flights list
        flights = list(flights)
        
        # Process each flight to add booking information
        for flight in flights:
            # Get reservation counts for this flight
            reservations = Reservation.objects.filter(flight=flight)
            flight.reservation_count = reservations.count()
            
            # Calculate booked seats manually instead of using property methods
            business_reservations = reservations.filter(type='1').exclude(status='2').count()
            economy_reservations = reservations.filter(type='2').exclude(status='2').count()
            
            # Instead of setting the properties directly, store them as different attributes
            flight._booked_business = business_reservations
            flight._booked_economy = economy_reservations
            
            # Calculate availability
            flight.available_economy = flight.economy_slots - economy_reservations
            flight.available_business = flight.business_class_slots - business_reservations
            
            # Calculate occupancy percentages
            if flight.economy_slots > 0:
                flight.economy_occupancy = float((economy_reservations / flight.economy_slots) * 100)
            else:
                flight.economy_occupancy = 0.0
                
            if flight.business_class_slots > 0:
                flight.business_occupancy = float((business_reservations / flight.business_class_slots) * 100)
            else:
                flight.business_occupancy = 0.0
            
            # Overall occupancy
            total_seats = flight.economy_slots + flight.business_class_slots
            if total_seats > 0:
                flight.overall_occupancy = float(((economy_reservations + business_reservations) / total_seats) * 100)
            else:
                flight.overall_occupancy = 0.0
        
        # Apply sorting
        if sort_by == 'code':
            flights = sorted(flights, key=lambda f: f.code)
        elif sort_by == 'airline':
            flights = sorted(flights, key=lambda f: f.airline.name)
        elif sort_by == 'from_airport':
            flights = sorted(flights, key=lambda f: f.from_airport.code)
        elif sort_by == 'to_airport':
            flights = sorted(flights, key=lambda f: f.to_airport.code)
        elif sort_by == 'occupancy':
            flights = sorted(flights, key=lambda f: f.overall_occupancy, reverse=True)
        elif sort_by == 'reservation_count':
            flights = sorted(flights, key=lambda f: f.reservation_count, reverse=True)
        else:  # Default sort by departure
            flights = sorted(flights, key=lambda f: f.departure)
        
        # Get filter options for dropdowns
        airlines = Airlines.objects.filter(status='1').order_by('name')
        airports = Airport.objects.filter(status='1').order_by('name')
        aircraft = Aircraft.objects.filter(status='1').order_by('model')
        
        # Get recurring flight schedules
        schedules = FlightSchedule.objects.filter(is_active=True, end_date__gte=today)
        
        context = {
            'title': 'Upcoming Flights',
            'flights': flights,
            'today': today,
            'end_date': end_date,
            'days': days,
            'days_options': [1, 3, 7, 14, 30],
            'airlines': airlines,
            'airports': airports,
            'aircraft': aircraft,
            'schedules': schedules,
            'selected_airline': airline_id,
            'selected_airport': airport_id,
            'selected_aircraft': aircraft_id,
            'selected_status': status,
            'date_from': date_from,
            'date_to': date_to,
            'sort_by': sort_by,
            'opts': {
                'app_label': 'armsApp',
                'verbose_name_plural': 'Upcoming Flights',
            },
            **self.admin_site.each_context(request),
        }
        
        return render(request, 'admin/upcoming_flights.html', context)


class ReservationApprovalAdminView:
    """
    Admin view to approve/reject reservations
    """
    
    def __init__(self, admin_site):
        self.admin_site = admin_site
    
    def get_urls(self):
        urls = [
            path('reservation-approval/', self.admin_site.admin_view(self.reservation_approval_view), name='reservation-approval'),
            path('approve-reservation/<int:pk>/', self.admin_site.admin_view(self.approve_reservation), name='approve-reservation'),
            path('reject-reservation/<int:pk>/', self.admin_site.admin_view(self.reject_reservation), name='reject-reservation'),
        ]
        return urls
    
    def reservation_approval_view(self, request):
        from django.contrib import messages
        
        # Get filter parameters
        status = request.GET.get('status', '0')  # Default to pending
        flight_id = request.GET.get('flight')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        
        # Build query
        reservations = Reservation.objects.select_related('flight', 'user', 'flight__airline', 'flight__from_airport', 'flight__to_airport').all()
        
        if status:
            reservations = reservations.filter(status=status)
        
        if flight_id:
            reservations = reservations.filter(flight_id=flight_id)
            
        if date_from:
            try:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                reservations = reservations.filter(date_added__date__gte=date_from)
            except ValueError:
                pass
                
        if date_to:
            try:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                reservations = reservations.filter(date_added__date__lte=date_to)
            except ValueError:
                pass
        
        reservations = reservations.order_by('-date_added')
        
        # Get available flights for filter
        flights = Flights.objects.all().order_by('code')
        
        # Get statistics
        stats = {
            'pending': Reservation.objects.filter(status='0').count(),
            'approved': Reservation.objects.filter(status='1').count(),
            'cancelled': Reservation.objects.filter(status='2').count(),
            'rejected': Reservation.objects.filter(status='3').count(),
        }
        
        context = {
            'title': 'Reservation Approval Management',
            'reservations': reservations,
            'flights': flights,
            'stats': stats,
            'selected_status': status,
            'selected_flight': flight_id,
            'date_from': date_from,
            'date_to': date_to,
            'opts': {
                'app_label': 'armsApp',
                'verbose_name_plural': 'Reservation Approvals',
            },
            **self.admin_site.each_context(request),
        }
        
        return render(request, 'admin/reservation_approval.html', context)
    
    def approve_reservation(self, request, pk):
        from django.contrib import messages
        from django.shortcuts import redirect
        
        try:
            reservation = Reservation.objects.get(id=pk)
            if reservation.approve_reservation():
                messages.success(request, f'Reservation for {reservation.name()} has been approved successfully.')
            else:
                messages.error(request, 'This reservation cannot be approved.')
        except Reservation.DoesNotExist:
            messages.error(request, 'Reservation not found.')
        except Exception as e:
            messages.error(request, f'Error approving reservation: {str(e)}')
            
        return redirect('admin:reservation-approval')
    
    def reject_reservation(self, request, pk):
        from django.contrib import messages
        from django.shortcuts import redirect
        
        try:
            reservation = Reservation.objects.get(id=pk)
            if reservation.reject_reservation():
                messages.success(request, f'Reservation for {reservation.name()} has been rejected.')
            else:
                messages.error(request, 'This reservation cannot be rejected.')
        except Reservation.DoesNotExist:
            messages.error(request, 'Reservation not found.')
        except Exception as e:
            messages.error(request, f'Error rejecting reservation: {str(e)}')
            
        return redirect('admin:reservation-approval')
