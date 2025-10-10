from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Fix the UserProfile table and migration issues'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Create the UserProfile table if it doesn't exist
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS "armsApp_userprofile" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "custom_id" varchar(50) NOT NULL UNIQUE,
                "mobile" varchar(20) NOT NULL,
                "is_admin" bool NOT NULL,
                "date_added" datetime NOT NULL,
                "date_updated" datetime NOT NULL,
                "user_id" integer NOT NULL UNIQUE REFERENCES "auth_user" ("id") ON DELETE CASCADE
            );
            """)
            
            # Fix the migration records
            cursor.execute("""
            INSERT OR IGNORE INTO django_migrations (app, name, applied) 
            VALUES ('armsApp', '0007_userprofile_reservation_user_reservation_seat_number', datetime('now'));
            """)
            
            cursor.execute("""
            INSERT OR IGNORE INTO django_migrations (app, name, applied) 
            VALUES ('armsApp', '0008_rename_user_id_userprofile_custom_id', datetime('now'));
            """)
            
            cursor.execute("""
            INSERT OR IGNORE INTO django_migrations (app, name, applied) 
            VALUES ('armsApp', '0009_fix_userprofile', datetime('now'));
            """)
        
        self.stdout.write(self.style.SUCCESS('Successfully fixed database issues'))
