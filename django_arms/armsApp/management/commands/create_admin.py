from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from armsApp.models import UserProfile
from django.utils import timezone

class Command(BaseCommand):
    help = 'Creates an admin user account if one does not exist'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default='admin', help='Admin username')
        parser.add_argument('--password', type=str, default='admin123', help='Admin password')
        parser.add_argument('--email', type=str, default='admin@example.com', help='Admin email')

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        email = options['email']
        
        # Check if admin user already exists
        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'Admin user "{username}" already exists'))
            
            # Make sure the user is properly set as admin
            user = User.objects.get(username=username)
            
            try:
                profile = UserProfile.objects.get(user=user)
                if profile.user_type != 'admin':
                    profile.user_type = 'admin'
                    profile.is_admin = True
                    profile.save()
                    self.stdout.write(self.style.SUCCESS(f'Updated user "{username}" to admin role'))
            except UserProfile.DoesNotExist:
                # Create profile if it doesn't exist
                profile = UserProfile.objects.create(
                    user=user,
                    custom_id=f"ADMIN{user.id}",
                    mobile="",
                    is_admin=True,
                    user_type='admin',
                    date_added=timezone.now(),
                    date_updated=timezone.now()
                )
                self.stdout.write(self.style.SUCCESS(f'Created admin profile for existing user "{username}"'))
                
            return
        
        # Create a new admin user
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
