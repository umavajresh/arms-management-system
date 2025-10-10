from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Fix the Reservation table by adding the user_id column'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Check if the column exists
            try:
                cursor.execute("SELECT user_id FROM armsApp_reservation LIMIT 1")
                self.stdout.write(self.style.SUCCESS('user_id column already exists'))
            except:
                # Add the user_id column to the reservation table
                self.stdout.write('Adding user_id column to the reservation table...')
                try:
                    cursor.execute("""
                    ALTER TABLE armsApp_reservation 
                    ADD COLUMN user_id integer NULL 
                    REFERENCES auth_user(id) ON DELETE CASCADE;
                    """)
                    self.stdout.write(self.style.SUCCESS('Successfully added user_id column'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error adding column: {str(e)}'))
            
            # Check if the seat_number column exists
            try:
                cursor.execute("SELECT seat_number FROM armsApp_reservation LIMIT 1")
                self.stdout.write(self.style.SUCCESS('seat_number column already exists'))
            except:
                # Add the seat_number column to the reservation table
                self.stdout.write('Adding seat_number column to the reservation table...')
                try:
                    cursor.execute("""
                    ALTER TABLE armsApp_reservation 
                    ADD COLUMN seat_number varchar(10) NULL;
                    """)
                    self.stdout.write(self.style.SUCCESS('Successfully added seat_number column'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error adding column: {str(e)}'))
                
        self.stdout.write(self.style.SUCCESS('Database fix operation completed'))
