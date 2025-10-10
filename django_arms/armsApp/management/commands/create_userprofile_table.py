from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Creates the UserProfile table if it does not exist'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS armsApp_userprofile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                custom_id VARCHAR(50) UNIQUE NOT NULL,
                mobile VARCHAR(20) NOT NULL,
                is_admin BOOLEAN NOT NULL,
                date_added DATETIME NOT NULL,
                date_updated DATETIME NOT NULL,
                user_id INTEGER UNIQUE NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE
            );
            """)
        
        self.stdout.write(self.style.SUCCESS('Successfully created UserProfile table'))
