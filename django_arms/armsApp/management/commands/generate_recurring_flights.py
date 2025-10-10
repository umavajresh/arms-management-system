import csv
import os
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, time, timedelta
from armsApp.models import Airlines, Airport, Aircraft, Flights, FlightSchedule

class Command(BaseCommand):
    help = 'Generate recurring flights from flight schedules'
    
    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30,
                            help='Number of days to generate flights for')
        parser.add_argument('--clear', action='store_true',
                            help='Clear existing future flights before generating new ones')
        parser.add_argument('--schedules', nargs='*', type=str,
                            help='Specific schedule codes to process (optional)')
    
    def handle(self, *args, **options):
        days = options['days']
        clear = options['clear']
        specific_schedules = options.get('schedules')
        
        today = timezone.now().date()
        end_date = today + timedelta(days=days)
        
        self.stdout.write(f"Generating recurring flights from {today} to {end_date}")
        
        # Clear future flights if requested
        if clear:
            future_flights = Flights.objects.filter(
                departure__date__gte=today
            )
            count = future_flights.count()
            future_flights.delete()
            self.stdout.write(self.style.WARNING(f"Deleted {count} future flights"))
        
        # Get active flight schedules
        schedules_query = FlightSchedule.objects.filter(
            is_active=True,
            delete_flag=0,
            end_date__gte=today
        )
        
        # Filter by specific codes if provided
        if specific_schedules:
            schedules_query = schedules_query.filter(code__in=specific_schedules)
            
        schedules = schedules_query.all()
        
        if not schedules:
            # If no schedules exist, fall back to generating from template flights
            self.generate_from_templates(today, end_date)
            return
            
        self.stdout.write(f"Processing {schedules.count()} active flight schedules")
        
        total_flights_created = 0
        for schedule in schedules:
            # For each schedule, generate flights up to the specified end date
            schedule_end_date = min(end_date, schedule.end_date)
            flights_created = schedule.generate_flights_for_date_range(today, schedule_end_date)
            
            self.stdout.write(f"  - {schedule.code}: {flights_created} flights generated")
            total_flights_created += flights_created
        
        self.stdout.write(self.style.SUCCESS(f"Created {total_flights_created} new recurring flights from schedules"))
        
    def generate_from_templates(self, start_date, end_date):
        """Fall back to generating flights from existing flights as templates"""
        self.stdout.write(self.style.WARNING("No flight schedules found, falling back to template-based generation"))
        
        # Get existing flights as templates
        template_flights = Flights.objects.all()
        self.stdout.write(f"Found {template_flights.count()} template flights")
        
        flights_created = 0
        
        # For each template flight, generate recurring instances
        for template in template_flights:
            # Get the departure time from the template
            departure_time = template.departure.time()
            
            # For each day in the range
            current_date = start_date
            while current_date <= end_date:
                # Generate a new departure datetime for this date
                new_departure = datetime.combine(
                    current_date,
                    departure_time,
                    tzinfo=template.departure.tzinfo or timezone.get_current_timezone()
                )
                
                # Calculate flight duration from the template
                duration = template.estimated_arrival - template.departure
                
                # Calculate new arrival time
                new_arrival = new_departure + duration
                
                # Generate a new flight code with date
                date_suffix = current_date.strftime('%m%d')
                new_code = f"{template.code}-{date_suffix}"
                
                # Check if this flight already exists
                if not Flights.objects.filter(
                    code=new_code,
                    departure__date=current_date
                ).exists():
                    # Create a new flight based on the template
                    new_flight = Flights(
                        code=new_code,
                        airline=template.airline,
                        from_airport=template.from_airport,
                        to_airport=template.to_airport,
                        aircraft=template.aircraft,
                        departure=new_departure,
                        estimated_arrival=new_arrival,
                        business_class_price=template.business_class_price,
                        economy_price=template.economy_price,
                        business_class_slots=template.aircraft.business_capacity,
                        economy_slots=template.aircraft.economy_capacity,
                        delete_flag=0,
                        date_added=timezone.now()
                    )
                    new_flight.save()
                    flights_created += 1
                
                # Move to next day
                current_date += timedelta(days=1)
        
        self.stdout.write(self.style.SUCCESS(f"Created {flights_created} new recurring flights from templates"))
