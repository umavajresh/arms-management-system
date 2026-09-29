import csv
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from armsApp.models import Airlines, Airport, Aircraft, Flights
from django.utils import timezone
from datetime import datetime
from django.utils import timezone as dj_timezone

class Command(BaseCommand):
    help = 'Import data from CSV files into the database'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('Starting data import...'))
        
        # Get the base directory for data files
        base_dir = os.path.join(settings.BASE_DIR, 'armsApp', 'management', 'commands', 'data')
        
        # Import Airlines
        self.import_airlines(os.path.join(base_dir, 'airlines.csv'))
        
        # Import Airports
        self.import_airports(os.path.join(base_dir, 'airports.csv'))
        
        # Import Aircraft
        self.import_aircraft(os.path.join(base_dir, 'aircraft.csv'))
        
        # Import Flights with prices
        self.import_flights(os.path.join(base_dir, 'flights.csv'))
        
        self.stdout.write(self.style.SUCCESS('Data import completed successfully!'))
    
    def import_airlines(self, file_path):
        self.stdout.write('Importing Airlines...')
        count = 0
        
        # First store the old Airlines model save method
        original_save = Airlines.save
        
        # Create a simple save method that doesn't process images
        def simple_save(instance, *args, **kwargs):
            super(Airlines, instance).save(*args, **kwargs)
        
        # Temporarily replace the save method
        Airlines.save = simple_save
        
        try:
            with open(file_path, 'r') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    try:
                        airline, created = Airlines.objects.update_or_create(
                            code=row['code'],
                            defaults={
                                'name': row['name'],
                                'country': row['country'],
                                'status': row.get('status', '1')
                            }
                        )
                        if created:
                            count += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Error importing airline {row['code']}: {str(e)}"))
                        continue
        finally:
            # Restore the original save method
            Airlines.save = original_save
        
        self.stdout.write(self.style.SUCCESS(f'Imported {count} new airlines'))
    
    def import_airports(self, file_path):
        self.stdout.write('Importing Airports...')
        count = 0
        
        with open(file_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                airport, created = Airport.objects.update_or_create(
                    code=row['code'],
                    defaults={
                        'name': row['name'],
                        'city': row['city'],
                        'country': row['country'],
                        'status': row.get('status', '1')
                    }
                )
                if created:
                    count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Imported {count} new airports'))
    
    def import_aircraft(self, file_path):
        self.stdout.write('Importing Aircraft...')
        count = 0
        
        with open(file_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                aircraft, created = Aircraft.objects.update_or_create(
                    code=row['code'],
                    defaults={
                        'model': row['model'],
                        'manufacturer': row['manufacturer'],
                        'business_capacity': row['business_capacity'],
                        'economy_capacity': row['economy_capacity'],
                        'status': '1'  # Set as active by default
                    }
                )
                if created:
                    count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Imported {count} new aircraft'))
        
    def import_flights(self, file_path):
        self.stdout.write('Importing Flights with price information...')
        count = 0

        def ensure_airline(code):
            airline, _ = Airlines.objects.get_or_create(
                code=code,
                defaults={'name': code, 'country': 'Unknown'}
            )
            return airline

        def ensure_airport(code):
            airport, _ = Airport.objects.get_or_create(
                code=code,
                defaults={'name': code, 'city': 'Unknown', 'country': 'Unknown'}
            )
            return airport

        def ensure_aircraft(code):
            aircraft, _ = Aircraft.objects.get_or_create(
                code=code,
                defaults={
                    'model': code,
                    'manufacturer': 'Unknown',
                    'business_capacity': 0,
                    'economy_capacity': 0,
                    'status': '1'
                }
            )
            return aircraft
        
        try:
            with open(file_path, 'r') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    try:
                        # Get related objects
                        airline = ensure_airline(row['airline_code'])
                        from_airport = ensure_airport(row['from_airport_code'])
                        to_airport = ensure_airport(row['to_airport_code'])
                        aircraft = ensure_aircraft(row['aircraft_code'])
                        
                        # Parse dates
                        departure = datetime.fromisoformat(row['departure'])
                        arrival = datetime.fromisoformat(row['estimated_arrival'])
                        if departure.tzinfo is None:
                            departure = dj_timezone.make_aware(departure)
                        if arrival.tzinfo is None:
                            arrival = dj_timezone.make_aware(arrival)
                        
                        # Create or update flight
                        flight, created = Flights.objects.update_or_create(
                            code=row['code'],
                            defaults={
                                'airline': airline,
                                'from_airport': from_airport,
                                'to_airport': to_airport,
                                'aircraft': aircraft,
                                'departure': departure,
                                'estimated_arrival': arrival,
                                'business_class_price': float(row['business_class_price']),
                                'economy_price': float(row['economy_price']),
                                'business_class_slots': aircraft.business_capacity,
                                'economy_slots': aircraft.economy_capacity,
                                'delete_flag': 0
                            }
                        )
                        
                        if created:
                            count += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'Error importing flight {row["code"]}: {str(e)}'))
            
            self.stdout.write(self.style.SUCCESS(f'Imported {count} new flights with price information'))
        except FileNotFoundError:
            self.stdout.write(self.style.WARNING(f'Flight data file not found at {file_path}'))
