from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from armsApp.models import Flights

class Command(BaseCommand):
    help = 'List upcoming flights for admin dashboard'
    
    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7,
                            help='Number of days to show upcoming flights for (default: 7)')
        parser.add_argument('--airline', type=str,
                            help='Filter by airline code (optional)')
        parser.add_argument('--airport', type=str,
                            help='Filter by departure or arrival airport code (optional)')
    
    def handle(self, *args, **options):
        days = options['days']
        airline_filter = options.get('airline')
        airport_filter = options.get('airport')
        
        today = timezone.now().date()
        end_date = today + timedelta(days=days)
        
        # Base queryset
        flights = Flights.objects.filter(
            departure__date__gte=today,
            departure__date__lte=end_date
        ).order_by('departure')
        
        # Apply filters if provided
        if airline_filter:
            flights = flights.filter(airline__code__iexact=airline_filter)
            
        if airport_filter:
            flights = flights.filter(
                from_airport__code__iexact=airport_filter
            ) | flights.filter(
                to_airport__code__iexact=airport_filter
            )
        
        # Print results
        self.stdout.write(self.style.SUCCESS(f"Upcoming Flights ({today} to {end_date}):"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        
        for flight in flights:
            self.stdout.write(
                f"{flight.code} | "
                f"{flight.airline.name} | "
                f"{flight.from_airport.code} → {flight.to_airport.code} | "
                f"{flight.departure.strftime('%Y-%m-%d %H:%M')} | "
                f"Economy: {flight.economy_slots - flight.booked_economy} | "
                f"Business: {flight.business_class_slots - flight.booked_business}"
            )
        
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS(f"Total: {flights.count()} flights found"))
