from django.core.management.base import BaseCommand
from armsApp.models import Flights, Airport
from django.db.models import Avg, Min, Max, Count
from django.db.models.functions import Round

class Command(BaseCommand):
    help = 'Displays price statistics for flights in the system'

    def handle(self, *args, **kwargs):
        # Get all airports in India
        indian_airports = Airport.objects.filter(country="India").values_list('id', flat=True)
        
        # Get statistics for domestic Indian flights
        domestic_flights = Flights.objects.filter(
            from_airport__in=indian_airports,
            to_airport__in=indian_airports,
            delete_flag=0
        )
        
        # Count flights
        domestic_count = domestic_flights.count()
        total_count = Flights.objects.filter(delete_flag=0).count()
        
        # Get price stats for economy class
        economy_stats = domestic_flights.aggregate(
            avg=Round(Avg('economy_price'), 2),
            min=Min('economy_price'),
            max=Max('economy_price')
        )
        
        # Get price stats for business class
        business_stats = domestic_flights.aggregate(
            avg=Round(Avg('business_class_price'), 2),
            min=Min('business_class_price'),
            max=Max('business_class_price')
        )
        
        # Display statistics
        self.stdout.write(self.style.SUCCESS(f"Flight Price Statistics"))
        self.stdout.write("-" * 50)
        self.stdout.write(f"Total flights: {total_count}")
        self.stdout.write(f"Domestic Indian flights: {domestic_count}")
        self.stdout.write(f"Percentage of domestic flights: {(domestic_count/total_count)*100:.2f}%")
        self.stdout.write("\nEconomy Class Prices (INR):")
        self.stdout.write(f"  Average: ₹{economy_stats['avg']}")
        self.stdout.write(f"  Minimum: ₹{economy_stats['min']}")
        self.stdout.write(f"  Maximum: ₹{economy_stats['max']}")
        self.stdout.write("\nBusiness Class Prices (INR):")
        self.stdout.write(f"  Average: ₹{business_stats['avg']}")
        self.stdout.write(f"  Minimum: ₹{business_stats['min']}")
        self.stdout.write(f"  Maximum: ₹{business_stats['max']}")
        
        # Popular routes
        self.stdout.write("\nTop 5 Domestic Routes:")
        top_routes = domestic_flights.values(
            'from_airport__name', 
            'to_airport__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:5]
        
        for i, route in enumerate(top_routes, 1):
            self.stdout.write(f"  {i}. {route['from_airport__name']} to {route['to_airport__name']} - {route['count']} flights")