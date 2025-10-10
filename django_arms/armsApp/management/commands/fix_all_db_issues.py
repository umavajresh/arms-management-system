from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
import datetime

class Command(BaseCommand):
    help = 'Fix all database issues in one go'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # 1. Create the UserProfile table if it doesn't exist
            self.stdout.write('Creating/fixing UserProfile table...')
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS "armsApp_userprofile" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "custom_id" varchar(50) NOT NULL UNIQUE,
                "mobile" varchar(20) NOT NULL,
                "is_admin" boolean NOT NULL,
                "date_added" datetime NOT NULL,
                "date_updated" datetime NOT NULL,
                "user_id" integer NOT NULL UNIQUE REFERENCES "auth_user" ("id") ON DELETE CASCADE,
                "user_type" varchar(10) NOT NULL DEFAULT 'user'
            );
            """)
            
            # 2. Add necessary columns to the Reservation table
            self.stdout.write('Adding columns to Reservation table...')
            # Check if user_id column exists
            try:
                cursor.execute("SELECT user_id FROM armsApp_reservation LIMIT 1")
                self.stdout.write('  - user_id column already exists')
            except:
                try:
                    cursor.execute("""
                    ALTER TABLE armsApp_reservation 
                    ADD COLUMN user_id integer NULL 
                    REFERENCES auth_user(id) ON DELETE CASCADE;
                    """)
                    self.stdout.write('  - Added user_id column')
                except Exception as e:
                    self.stdout.write(f'  - Error adding user_id column: {str(e)}')
                    
            # Check if seat_number column exists
            try:
                cursor.execute("SELECT seat_number FROM armsApp_reservation LIMIT 1")
                self.stdout.write('  - seat_number column already exists')
            except:
                try:
                    cursor.execute("""
                    ALTER TABLE armsApp_reservation 
                    ADD COLUMN seat_number varchar(10) NULL;
                    """)
                    self.stdout.write('  - Added seat_number column')
                except Exception as e:
                    self.stdout.write(f'  - Error adding seat_number column: {str(e)}')
                    
            # Check if user_type column exists in UserProfile table
            try:
                cursor.execute("SELECT user_type FROM armsApp_userprofile LIMIT 1")
                self.stdout.write('  - user_type column already exists')
            except:
                try:
                    cursor.execute("""
                    ALTER TABLE armsApp_userprofile 
                    ADD COLUMN user_type varchar(10) NOT NULL DEFAULT 'user';
                    """)
                    self.stdout.write('  - Added user_type column')
                    
                    # Set existing admin users to have admin user_type
                    cursor.execute("""
                    UPDATE armsApp_userprofile
                    SET user_type = 'admin'
                    WHERE is_admin = 1;
                    """)
                    self.stdout.write('  - Updated user_type for existing admin users')
                except Exception as e:
                    self.stdout.write(f'  - Error adding user_type column: {str(e)}')
            
            # 3. Fix migration records
            self.stdout.write('Fixing migration records...')
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Check for each migration and fix if needed
            migrations = [
                ('0007_userprofile_reservation_user_reservation_seat_number', now),
                ('0008_rename_user_id_userprofile_custom_id', now),
                ('0009_fix_userprofile', now)
            ]
            
            for migration_name, applied_time in migrations:
                # Check if migration exists
                cursor.execute(
                    "SELECT id FROM django_migrations WHERE app = 'armsApp' AND name = %s",
                    [migration_name]
                )
                result = cursor.fetchone()
                
                if result:
                    # Update the existing record to mark as applied
                    cursor.execute(
                        "UPDATE django_migrations SET applied = %s WHERE app = 'armsApp' AND name = %s",
                        [applied_time, migration_name]
                    )
                    self.stdout.write(f'  - Updated migration: {migration_name}')
                else:
                    # Insert a new record
                    cursor.execute(
                        "INSERT INTO django_migrations (app, name, applied) VALUES ('armsApp', %s, %s)",
                        [migration_name, applied_time]
                    )
                    self.stdout.write(f'  - Added migration: {migration_name}')
        
        self.stdout.write(self.style.SUCCESS('All database fixes completed successfully!'))
