from django.core.management.base import BaseCommand
from django.template.loaders import filesystem, app_directories
import os
import shutil

class Command(BaseCommand):
    help = 'Clears the Django template cache'

    def handle(self, *args, **options):
        # Clear __pycache__ directories in template directories
        try:
            # Remove templatetags __pycache__ directory
            template_cache_dir = os.path.join('armsApp', 'templatetags', '__pycache__')
            if os.path.exists(template_cache_dir):
                shutil.rmtree(template_cache_dir)
                self.stdout.write(self.style.SUCCESS(f'Removed {template_cache_dir}'))
            else:
                self.stdout.write(self.style.WARNING(f'{template_cache_dir} does not exist'))
                
            # Recreate the directory
            os.makedirs(template_cache_dir, exist_ok=True)
            self.stdout.write(self.style.SUCCESS(f'Created empty {template_cache_dir}'))
                
            self.stdout.write(self.style.SUCCESS('Successfully cleared template cache'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error clearing cache: {str(e)}'))