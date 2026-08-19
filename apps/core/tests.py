"""Base test classes and utilities."""

from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class BaseTestCase(TestCase):
    """Base test case with common utilities."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        super().setUpTestData()
        cls.user = cls.create_user()
        cls.admin = cls.create_user(
            username='admin',
            email='admin@test.com',
            is_staff=True,
            is_superuser=True
        )
    
    @staticmethod
    def create_user(**kwargs):
        """Create a test user."""
        defaults = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'testpass123',
            'first_name': 'Test',
            'last_name': 'User'
        }
        defaults.update(kwargs)
        
        password = defaults.pop('password')
        user = User.objects.create(**defaults)
        user.set_password(password)
        user.save()
        return user


class BaseAPITestCase(APITestCase):
    """Base API test case with authentication."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        super().setUpTestData()
        cls.user = cls.create_user()
        cls.admin = cls.create_user(
            username='admin',
            email='admin@test.com',
            is_staff=True,
            is_superuser=True
        )
    
    def setUp(self):
        """Set up test client."""
        super().setUp()
        self.client = APIClient()
    
    @staticmethod
    def create_user(**kwargs):
        """Create a test user."""
        defaults = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'testpass123',
            'first_name': 'Test',
            'last_name': 'User'
        }
        defaults.update(kwargs)
        
        password = defaults.pop('password')
        user = User.objects.create(**defaults)
        user.set_password(password)
        user.save()
        return user
    
    def authenticate(self, user=None):
        """Authenticate API client with JWT."""
        user = user or self.user
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    
    def unauthenticate(self):
        """Remove authentication."""
        self.client.credentials()


class BaseTransactionTestCase(TransactionTestCase):
    """Base transaction test case for tests requiring database transactions."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.user = self.create_user()
        self.admin = self.create_user(
            username='admin',
            email='admin@test.com',
            is_staff=True,
            is_superuser=True
        )
    
    @staticmethod
    def create_user(**kwargs):
        """Create a test user."""
        defaults = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'testpass123',
            'first_name': 'Test',
            'last_name': 'User'
        }
        defaults.update(kwargs)
        
        password = defaults.pop('password')
        user = User.objects.create(**defaults)
        user.set_password(password)
        user.save()
        return user
