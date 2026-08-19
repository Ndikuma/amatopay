"""Seed database with test data."""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    """Seed database with initial test data."""
    
    help = 'Seed database with test data for development'
    
    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing data before seeding',
        )
    
    def handle(self, *args, **options):
        """Execute command."""
        if options['clear']:
            self.stdout.write('Clearing existing data...')
            # Add clearing logic here
        
        self.stdout.write('Seeding users...')
        self._seed_users()
        
        self.stdout.write(self.style.SUCCESS('✓ Data seeding completed'))
    
    def _seed_users(self):
        """Create test users."""
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser(
                username='admin',
                email='admin@amatopay.com',
                password='admin123',
                first_name='Admin',
                last_name='User'
            )
            self.stdout.write('  ✓ Created admin user')
        
        if not User.objects.filter(username='testuser').exists():
            User.objects.create_user(
                username='testuser',
                email='test@amatopay.com',
                password='test123',
                first_name='Test',
                last_name='User'
            )
            self.stdout.write('  ✓ Created test user')
