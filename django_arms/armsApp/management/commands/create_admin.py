from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from armsApp.models import UserProfile
from django.utils import timezone

class Command(BaseCommand):
    help = 'Creates an admin user account if one does not exist'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default='admin', help='Admin username')
        parser.add_argument('--email', type=str, default='admin@example.com', help='Admin email')

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        
        if User.objects.filter(username=username).exists():
            raise CommandError(
                f'User "{username}" already exists. Refusing to change an existing account role.'
            )

        password = getpass('Admin password: ')
        if not password:
            raise CommandError('An admin password is required.')
        if password != getpass('Confirm admin password: '):
            raise CommandError('Passwords do not match.')
        try:
            validate_password(password, user=User(username=username, email=email))
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages)) from exc
        
        try:
            admin = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=True,
                is_active=True
            )
            
            # Create the admin profile
            profile = UserProfile.objects.create(
                user=admin,
                custom_id=f"ADMIN{admin.id}",
                mobile="",
                is_admin=True,
                user_type='admin',
                date_added=timezone.now(),
                date_updated=timezone.now()
            )
            
            self.stdout.write(self.style.SUCCESS(f'Admin user "{username}" created successfully'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating admin user: {str(e)}'))
