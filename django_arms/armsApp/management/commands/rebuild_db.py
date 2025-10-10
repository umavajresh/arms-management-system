import os
from django.core.management.base import BaseCommand
from django.core import management
from django.db import connection


class Command(BaseCommand):
    help = 'Rebuild the database from scratch'

    def handle(self, *args, **kwargs):
        # Check if database file exists and delete it
        try:
            os.remove('db.sqlite3')
            self.stdout.write(self.style.SUCCESS('Removed existing database file'))
        except:
            self.stdout.write('No database file to remove')
        
        # Run basic migrations (non-problematic ones)
        self.stdout.write('Running initial migrations...')
        management.call_command('migrate', 'contenttypes')
        management.call_command('migrate', 'auth')
        management.call_command('migrate', 'admin')
        management.call_command('migrate', 'sessions')
        
        # Create basic tables for armsApp manually
        self.stdout.write('Creating armsApp tables...')
        with connection.cursor() as cursor:
            # Create Airlines table
            cursor.execute('''
            CREATE TABLE "armsApp_airlines" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "code" varchar(5) NOT NULL UNIQUE,
                "name" varchar(250) NOT NULL,
                "country" varchar(100) NULL,
                "image_path" varchar(100) NULL,
                "status" varchar(2) NOT NULL,
                "delete_flag" integer NOT NULL,
                "date_added" datetime NOT NULL,
                "date_created" datetime NOT NULL
            )
            ''')
            
            # Create Airport table
            cursor.execute('''
            CREATE TABLE "armsApp_airport" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "code" varchar(5) NOT NULL UNIQUE,
                "name" varchar(250) NOT NULL,
                "city" varchar(100) NULL,
                "country" varchar(100) NULL,
                "status" varchar(2) NOT NULL,
                "delete_flag" integer NOT NULL,
                "date_added" datetime NOT NULL,
                "date_created" datetime NOT NULL
            )
            ''')
            
            # Create Aircraft table
            cursor.execute('''
            CREATE TABLE "armsApp_aircraft" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "code" varchar(5) NOT NULL UNIQUE,
                "model" varchar(250) NOT NULL,
                "manufacturer" varchar(100) NOT NULL,
                "business_capacity" integer NOT NULL,
                "economy_capacity" integer NOT NULL,
                "status" varchar(2) NOT NULL,
                "delete_flag" integer NOT NULL,
                "date_added" datetime NOT NULL,
                "date_created" datetime NOT NULL
            )
            ''')
            
            # Create Flights table with aircraft_id
            cursor.execute('''
            CREATE TABLE "armsApp_flights" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "code" varchar(250) NOT NULL,
                "airline_id" integer NOT NULL REFERENCES "armsApp_airlines" ("id") DEFERRABLE INITIALLY DEFERRED,
                "from_airport_id" integer NOT NULL REFERENCES "armsApp_airport" ("id") DEFERRABLE INITIALLY DEFERRED,
                "to_airport_id" integer NOT NULL REFERENCES "armsApp_airport" ("id") DEFERRABLE INITIALLY DEFERRED,
                "aircraft_id" integer NULL REFERENCES "armsApp_aircraft" ("id") DEFERRABLE INITIALLY DEFERRED,
                "departure" datetime NOT NULL,
                "estimated_arrival" datetime NOT NULL,
                "business_class_slots" integer NOT NULL,
                "economy_slots" integer NOT NULL,
                "business_class_price" real NOT NULL,
                "economy_price" real NOT NULL,
                "delete_flag" integer NOT NULL,
                "date_added" datetime NOT NULL,
                "date_created" datetime NOT NULL
            )
            ''')
            
            # Create UserProfile table
            cursor.execute('''
            CREATE TABLE "armsApp_userprofile" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "custom_id" varchar(50) NOT NULL UNIQUE,
                "mobile" varchar(20) NOT NULL,
                "is_admin" bool NOT NULL,
                "user_type" varchar(10) NOT NULL,
                "date_added" datetime NOT NULL,
                "date_updated" datetime NOT NULL,
                "user_id" integer NOT NULL UNIQUE REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED
            )
            ''')
            
            # Create Reservation table
            cursor.execute('''
            CREATE TABLE "armsApp_reservation" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "flight_id" integer NOT NULL REFERENCES "armsApp_flights" ("id") DEFERRABLE INITIALLY DEFERRED,
                "user_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED,
                "type" varchar(50) NOT NULL,
                "first_name" varchar(250) NOT NULL,
                "middle_name" varchar(250) NOT NULL,
                "last_name" varchar(250) NOT NULL,
                "gender" varchar(50) NOT NULL,
                "email" varchar(250) NOT NULL,
                "contact" varchar(250) NOT NULL,
                "address" text NOT NULL,
                "status" varchar(2) NOT NULL,
                "date_added" datetime NOT NULL,
                "date_created" datetime NOT NULL,
                "seat_number" varchar(10) NULL
            )
            ''')

        # Add a record to django_migrations to mark all migrations as applied
        self.stdout.write('Marking migrations as applied...')
        with connection.cursor() as cursor:
            # Create migrations table if it doesn't exist
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS "django_migrations" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "app" varchar(255) NOT NULL,
                "name" varchar(255) NOT NULL,
                "applied" datetime NOT NULL
            )
            ''')
            
            # Insert all migration records
            for i in range(1, 12):  # Add all migration files
                migration_name = f"000{i}" if i < 10 else f"00{i}"
                cursor.execute(
                    'INSERT INTO django_migrations (app, name, applied) VALUES (?, ?, datetime("now"))',
                    ['armsApp', migration_name, ]
                )
        
        self.stdout.write(self.style.SUCCESS('Database rebuilt successfully'))
