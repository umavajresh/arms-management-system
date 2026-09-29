from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from armsApp.models import Aircraft, Airport, Airlines, Flights, UserProfile
from armsApp.views import _fetch_live_flight_data

from armsApp.ai_chatbot import extract_travel_preferences, get_travel_response


class LoginAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='login-test-user',
            password='Valid-login-password-42',
        )
        UserProfile.objects.create(
            user=cls.user,
            custom_id='LOGIN-TEST-42',
            mobile='5550100',
        )

    def test_username_and_custom_id_create_independent_one_day_sessions(self):
        clients = (Client(), Client())
        identifiers = (self.user.username, 'LOGIN-TEST-42')

        for client, identifier in zip(clients, identifiers):
            response = client.post(
                reverse('login-user'),
                {'username': identifier, 'password': 'Valid-login-password-42'},
            )
            self.assertEqual(response.json()['status'], 'success')
            self.assertEqual(response.cookies['sessionid']['max-age'], 86400)

        for client in clients:
            self.assertEqual(client.session.get('_auth_user_id'), str(self.user.pk))


class RegistrationFlowTests(TestCase):
    def test_registration_form_creates_account_that_can_log_in(self):
        registration_page = self.client.get(reverse('register-page'))
        self.assertContains(
            registration_page,
            f'action="{reverse("register-user")}"',
        )

        response = self.client.post(
            reverse('register-user'),
            {
                'first_name': 'Test',
                'last_name': 'Passenger',
                'email': 'test.passenger@example.com',
                'custom_id': 'TEST-USER-2026',
                'mobile': '5550101',
                'username': 'test-passenger-2026',
                'date_of_birth': '1990-01-02',
                'security_question': 'nickname',
                'security_answer': 'test answer',
                'password1': 'Registration-Test-Password-42',
                'password2': 'Registration-Test-Password-42',
            },
        )
        self.assertEqual(response.json()['status'], 'success')

        user = User.objects.get(username='test-passenger-2026')
        self.assertTrue(user.check_password('Registration-Test-Password-42'))
        self.assertTrue(UserProfile.objects.filter(user=user, custom_id='TEST-USER-2026').exists())

        login_response = self.client.post(
            reverse('login-user'),
            {'username': 'TEST-USER-2026', 'password': 'Registration-Test-Password-42'},
        )
        self.assertEqual(login_response.json()['status'], 'success')


class TravelChatbotTests(SimpleTestCase):
    def test_extract_travel_preferences_budget_and_duration(self):
        prefs = extract_travel_preferences("I have a budget of ₹15,000 for 3 days from Chennai")
        self.assertEqual(prefs['budget'], 15000)
        self.assertEqual(prefs['days'], 3)
        self.assertIn("chennai", prefs['origin'].lower())

    def test_get_travel_response_returns_recommendations_when_prompt_has_budget(self):
        response = get_travel_response("My budget is ₹12,000 for 3 days")
        self.assertIn("₹", response)
        self.assertIn("Budget", response)


class ImportDataCommandTests(SimpleTestCase):
    databases = {'default'}

    def test_import_data_populates_real_flights(self):
        call_command('import_data')

        self.assertGreater(Flights.objects.count(), 0)
        self.assertTrue(any(flight.is_bookable() for flight in Flights.objects.all()))
        self.assertTrue(Airlines.objects.filter(code='BAW').exists())
        self.assertTrue(Airport.objects.filter(code='JNB').exists())
        self.assertTrue(Aircraft.objects.filter(code='B788').exists())


class LiveFlightTrackerTests(SimpleTestCase):
    @patch('armsApp.views.requests.get')
    def test_fetch_live_flight_data_uses_aviationstack(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'data': [{
                'flight': {'iata': 'BAW123'},
                'airline': {'name': 'British Airways'},
                'departure': {'airport': 'London Heathrow', 'scheduled': '2026-08-26T10:00:00+00:00'},
                'arrival': {'airport': 'New York JFK', 'scheduled': '2026-08-26T18:00:00+00:00'},
                'live': {
                    'latitude': 51.47,
                    'longitude': -0.45,
                    'altitude': 6500,
                    'speed_horizontal': 530,
                    'updated': '2026-08-26T11:00:00+00:00',
                },
                'status': 'active',
            }]
        }
        mock_get.return_value = mock_response

        with patch.dict('os.environ', {'AVIATIONSTACK_API_KEY': 'demo-key'}):
            result = _fetch_live_flight_data('BAW123')

        self.assertIsNotNone(result)
        self.assertEqual(result['flight_code'], 'BAW123')
        self.assertEqual(result['status'], 'active')
        self.assertEqual(result['latitude'], 51.47)
        self.assertEqual(result['longitude'], -0.45)
        self.assertEqual(result['airline'], 'British Airways')

    @patch('armsApp.views.requests.get')
    def test_fetch_live_flight_data_falls_back_to_opensky(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'states': [
                [
                    None, 'BAW123', None, None, None, -0.45, 51.47, 6500.0, None, 530.0,
                    None, None, None, None, None, None, None, None, None, None
                ]
            ]
        }
        mock_get.return_value = mock_response

        with patch.dict('os.environ', {}, clear=True):
            result = _fetch_live_flight_data('BAW123')

        self.assertIsNotNone(result)
        self.assertEqual(result['source'], 'opensky')
        self.assertEqual(result['flight_code'], 'BAW123')
        self.assertEqual(result['latitude'], 51.47)
        self.assertEqual(result['longitude'], -0.45)
