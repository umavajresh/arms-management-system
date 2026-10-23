import json
from datetime import date, timedelta
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone
from django.urls import reverse

from armsApp import models
from armsApp.models import Aircraft, Airport, Airlines, Flights, Reservation, UserProfile
from armsApp.views import _ai_chat_rate_limited, _fetch_live_flight_data

from armsApp.ai_chatbot import (
    _build_llm_grounding_context,
    extract_travel_preferences,
    get_llm_provider_status,
    get_travel_response,
    search_real_flights,
)


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


class PasswordRecoveryFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='recovery-test-user',
            password='Recovery-test-password-42',
        )
        UserProfile.objects.create(
            user=cls.user,
            custom_id='RECOVERY-TEST-USER',
            mobile='5550105',
            security_question='pet',
            security_answer=make_password('milo'),
            date_of_birth=date(1991, 4, 12),
        )

    def test_existing_and_unknown_identifiers_receive_the_same_recovery_step(self):
        existing_response = self.client.post(
            reverse('forgot-password'),
            {'username': self.user.username},
            follow=True,
        )
        unknown_response = self.client.post(
            reverse('forgot-password'),
            {'username': 'unknown-recovery-user'},
            follow=True,
        )

        self.assertEqual(existing_response.status_code, 200)
        self.assertEqual(unknown_response.status_code, 200)
        self.assertContains(existing_response, 'Your recovery question is hidden for privacy.')
        self.assertContains(unknown_response, 'Your recovery question is hidden for privacy.')
        self.assertNotContains(existing_response, 'What is your pet')

    def test_valid_recovery_resets_password_and_clears_flow_state(self):
        start_response = self.client.post(
            reverse('forgot-password'),
            {'username': 'RECOVERY-TEST-USER'},
        )
        self.assertRedirects(start_response, reverse('verify-identity'))

        verify_response = self.client.post(
            reverse('answer-security-question'),
            {
                'date_of_birth': '1991-04-12',
                'security_answer': 'MILO',
            },
        )
        self.assertRedirects(verify_response, reverse('reset-password'))

        reset_response = self.client.post(
            reverse('reset-password'),
            {
                'new_password': 'New-Recovery-Password-902!',
                'confirm_password': 'New-Recovery-Password-902!',
            },
        )
        self.assertRedirects(reset_response, reverse('login-page'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('New-Recovery-Password-902!'))
        self.assertTrue(check_password('milo', self.user.profile.security_answer))
        self.assertNotIn('reset_user_id', self.client.session)
        self.assertNotIn('identity_verified', self.client.session)

    def test_recovery_expires_and_limits_failed_attempts(self):
        self.client.post(
            reverse('forgot-password'),
            {'username': self.user.username},
        )
        session = self.client.session
        session['reset_expires_at'] = timezone.now().timestamp() - 1
        session.save()

        expired_response = self.client.get(reverse('verify-identity'))
        self.assertRedirects(expired_response, reverse('forgot-password'))
        self.assertNotIn('reset_user_id', self.client.session)

        self.client.post(
            reverse('forgot-password'),
            {'username': self.user.username},
        )
        for attempt in range(5):
            response = self.client.post(
                reverse('answer-security-question'),
                {'date_of_birth': '1991-04-12', 'security_answer': 'incorrect'},
            )
            if attempt < 4:
                self.assertEqual(response.status_code, 200)

        self.assertRedirects(response, reverse('forgot-password'))
        self.assertNotIn('reset_user_id', self.client.session)


class ReservationSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='reservation-test-user',
            password='Reservation-test-password-42',
        )
        cls.admin = User.objects.create_user(
            username='reservation-test-admin',
            password='Reservation-admin-password-42',
        )
        UserProfile.objects.create(
            user=cls.admin,
            custom_id='RESERVATION-TEST-ADMIN',
            mobile='5550104',
            is_admin=True,
            user_type='admin',
        )
        airline = Airlines.objects.create(code='RTA', name='Reservation Test Air')
        origin = Airport.objects.create(
            code='TST', name='Test Origin Airport', city='Origin', country='India'
        )
        destination = Airport.objects.create(
            code='DST', name='Test Destination Airport', city='Destination', country='India'
        )
        departure = timezone.now() + timedelta(days=14)
        cls.flight = Flights.objects.create(
            code='RTEST1',
            airline=airline,
            from_airport=origin,
            to_airport=destination,
            departure=departure,
            estimated_arrival=departure + timedelta(hours=2),
            business_class_slots=5,
            economy_slots=11,
            business_class_price=12000,
            economy_price=5000,
        )

    def _select_session_seat(self, seat='E1A', seat_type='2', seat_class='economy'):
        session = self.client.session
        session['selected_flight'] = str(self.flight.pk)
        session['selected_seats_data'] = json.dumps({
            'passenger_count': 1,
            'seats': [{'seat': seat, 'type': seat_type, 'class': seat_class}],
        })
        session['passenger_count'] = 1
        session.save()

    def _verify_reservation(self):
        session = self.client.session
        session['simple_captcha'] = '7'
        session.save()
        response = self.client.post(
            reverse('verify-reservation'),
            {
                'password': 'Reservation-test-password-42',
                'captcha_0': 'simple_math',
                'captcha_1': '7',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')

    def _reservation_data(self, **overrides):
        data = {
            'flight': str(self.flight.pk),
            'passenger_count': '1',
            'passenger_0_first_name': 'Test',
            'passenger_0_middle_name': '',
            'passenger_0_last_name': 'Passenger',
            'passenger_0_gender': 'Female',
            'passenger_0_seat': 'E1A',
            'passenger_0_type': '2',
            'email': 'test.passenger@example.com',
            'contact': '5550102',
            'address': '',
        }
        data.update(overrides)
        return data

    def test_reservation_requires_authentication_and_verification(self):
        self._select_session_seat()
        guest_response = self.client.post(
            reverse('save-reservation'),
            self._reservation_data(),
        )
        self.assertEqual(guest_response.status_code, 401)
        self.assertEqual(Reservation.objects.count(), 0)

        self.client.force_login(self.user)
        unverified_response = self.client.post(
            reverse('save-reservation'),
            self._reservation_data(),
        )
        self.assertEqual(unverified_response.status_code, 403)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_verified_single_passenger_booking_saves_server_selected_seat(self):
        self.client.force_login(self.user)
        self._select_session_seat()
        self._verify_reservation()

        response = self.client.post(
            reverse('save-reservation'),
            self._reservation_data(
                passenger_0_seat='B1A',
                passenger_0_type='1',
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'failed')
        self.assertEqual(Reservation.objects.count(), 0)

        response = self.client.post(
            reverse('save-reservation'),
            self._reservation_data(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        reservation = Reservation.objects.get()
        self.assertEqual(reservation.seat_number, 'E1A')
        self.assertEqual(reservation.type, '2')
        self.assertEqual(reservation.user, self.user)
        self.assertEqual(reservation.status, '0')
        self.assertNotIn('reservation_verified_until', self.client.session)

    def test_reservation_verification_locks_after_five_failures(self):
        self.client.force_login(self.user)

        for attempt in range(5):
            response = self.client.post(
                reverse('verify-reservation'),
                {
                    'password': 'incorrect-password',
                    'captcha_0': 'simple_math',
                    'captcha_1': '7',
                },
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['status'], 'failed')

    def test_admin_reservation_updates_only_allow_valid_transitions(self):
        self.client.force_login(self.admin)
        reservation = Reservation.objects.create(
            flight=self.flight,
            user=self.user,
            type='2',
            first_name='Test',
            last_name='Passenger',
            gender='Female',
            email='test.passenger@example.com',
            contact='5550102',
            seat_number='E1A',
        )

        invalid_response = self.client.post(
            reverse('update-reservation'),
            {'id': reservation.pk, 'status': '99'},
        )
        self.assertEqual(invalid_response.status_code, 400)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, '0')

        approval_response = self.client.post(
            reverse('update-reservation'),
            {'id': reservation.pk, 'status': '1'},
        )
        self.assertEqual(approval_response.status_code, 200)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, '1')

        duplicate_response = self.client.post(
            reverse('update-reservation'),
            {'id': reservation.pk, 'status': '1'},
        )
        self.assertEqual(duplicate_response.status_code, 409)

    def test_passenger_can_cancel_only_their_active_reservations(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            flight=self.flight,
            user=self.user,
            type='2',
            first_name='Test',
            last_name='Passenger',
            gender='Female',
            email='test.passenger@example.com',
            contact='5550102',
            seat_number='E1A',
            status='1',
        )

        response = self.client.post(
            reverse('cancel-reservation'),
            {'id': reservation.pk},
        )
        self.assertEqual(response.status_code, 200)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, '2')

        rejected = Reservation.objects.create(
            flight=self.flight,
            user=self.user,
            type='2',
            first_name='Test',
            last_name='Rejected',
            gender='Female',
            email='test.passenger@example.com',
            contact='5550102',
            seat_number='E1B',
            status='3',
        )
        response = self.client.post(
            reverse('cancel-reservation'),
            {'id': rejected.pk},
        )
        self.assertEqual(response.status_code, 409)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, '3')

        response = self.client.post(
            reverse('cancel-reservation'),
            {'id': 'not-a-reservation-id'},
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_double_book_occupied_seat(self):
        Reservation.objects.create(
            flight=self.flight,
            user=self.user,
            type='2',
            seat_number='E1A',
            first_name='Prior',
            last_name='Passenger',
            gender='Female',
            contact='5550100',
            email='prior@example.com',
            status='1',
        )
        self.client.force_login(self.user)
        self._select_session_seat(seat='E1A')
        self._verify_reservation()
        response = self.client.post(
            reverse('save-reservation'),
            self._reservation_data(passenger_0_seat='E1A'),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['status'], 'failed')

    def test_archiving_aircraft_preserves_flights_and_reservations(self):
        self.client.force_login(self.admin)
        aircraft = Aircraft.objects.create(
            code='ZTEST',
            model='Test aircraft',
            manufacturer='Test manufacturer',
            business_capacity=2,
            economy_capacity=8,
        )
        self.flight.aircraft = aircraft
        self.flight.save()
        reservation = Reservation.objects.create(
            flight=self.flight,
            user=self.user,
            type='2',
            first_name='Test',
            last_name='Passenger',
            gender='Female',
            email='test.passenger@example.com',
            contact='5550102',
            seat_number='E1A',
        )

        response = self.client.post(
            reverse('delete-aircraft-pk', args=[aircraft.pk]),
        )

        self.assertEqual(response.status_code, 200)
        aircraft.refresh_from_db()
        self.assertEqual(aircraft.delete_flag, 1)
        self.assertTrue(Flights.objects.filter(pk=self.flight.pk).exists())
        self.assertTrue(Reservation.objects.filter(pk=reservation.pk).exists())

    def test_admin_deletion_endpoints_reject_get_requests(self):
        self.client.force_login(self.admin)
        delete_routes = (
            'delete-airline-pk',
            'delete-airport-pk',
            'delete-flight-pk',
            'delete-reservation-pk',
            'delete-aircraft-pk',
        )

        for route_name in delete_routes:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name, args=[1]))
                self.assertEqual(response.status_code, 405)

    def test_seat_selection_rejects_fabricated_seat_codes(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('seat-selection', args=[self.flight.pk]),
            {
                'selected_seats': json.dumps({
                    'passenger_count': 1,
                    'seats': [{'seat': 'E999Z', 'class': 'economy'}],
                }),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('selected_seats_data', self.client.session)

    def test_seat_map_matches_configured_capacity_and_cabin_codes(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('seat-selection', args=[self.flight.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [seat['seat'] for seat in response.context['business_seats']],
            ['B1A', 'B1B', 'B1C', 'B1D', 'B2A'],
        )
        self.assertEqual(
            [seat['seat'] for seat in response.context['economy_seats']],
            ['E1A', 'E1B', 'E1C', 'E1D', 'E1E', 'E1F', 'E2A', 'E2B', 'E2C', 'E2D', 'E2E'],
        )

    def test_reservation_form_uses_a_json_script_for_server_selected_seats(self):
        self.client.force_login(self.user)
        self._select_session_seat()

        response = self.client.get(reverse('reserve-form', args=[self.flight.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="reservation-payload"')
        self.assertContains(response, '"seat": "E1A"')
        self.assertNotContains(response, "selected_seats|safe")


class RouteAuthorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.passenger = User.objects.create_user(
            username='route-test-passenger',
            password='Route-test-password-42',
        )
        UserProfile.objects.create(
            user=cls.passenger,
            custom_id='ROUTE-TEST-USER',
            mobile='5550103',
            user_type='user',
        )

    def test_anonymous_user_is_redirected_from_admin_routes_to_login(self):
        response = self.client.get(reverse('aircraft-page'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('login-page')))

    def test_passenger_cannot_read_or_write_aircraft_management(self):
        self.client.force_login(self.passenger)

        page_response = self.client.get(reverse('aircraft-page'))
        save_response = self.client.post(reverse('save-aircraft'), {})

        self.assertRedirects(page_response, reverse('user-dashboard'))
        self.assertRedirects(save_response, reverse('user-dashboard'))
        self.assertEqual(Aircraft.objects.count(), 0)

    def test_passenger_cannot_open_record_management_forms(self):
        self.client.force_login(self.passenger)
        protected_routes = (
            'manage-airline-pk',
            'manage-airport-pk',
            'manage-flight-pk',
        )

        for route_name in protected_routes:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name, args=[1]))
                self.assertRedirects(response, reverse('user-dashboard'))

    def test_passenger_cannot_execute_admin_modifications(self):
        self.client.force_login(self.passenger)
        for route_name, post_data in [
            ('save-airline', {'name': 'Unauthorized Air', 'code': 'UA1'}),
            ('save-airport', {'name': 'Unauthorized Airport', 'code': 'UA2'}),
            ('save-flight', {'code': 'UA3'}),
            ('delete-airline-pk', {}),
            ('delete-airport-pk', {}),
            ('delete-flight-pk', {}),
            ('delete-aircraft-pk', {}),
            ('update-reservation', {'id': '1', 'status': '1'}),
        ]:
            with self.subTest(route=route_name):
                url = reverse(route_name, args=[1]) if '-pk' in route_name else reverse(route_name)
                response = self.client.post(url, post_data)
                self.assertRedirects(response, reverse('user-dashboard'))


class ReservationCancellationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user1 = User.objects.create_user(
            username='cancel-user-1',
            password='Cancel-password-1!',
        )
        UserProfile.objects.create(
            user=cls.user1,
            custom_id='CANCEL-USER-1',
            mobile='5550111',
            user_type='user',
        )
        cls.user2 = User.objects.create_user(
            username='cancel-user-2',
            password='Cancel-password-2!',
        )
        UserProfile.objects.create(
            user=cls.user2,
            custom_id='CANCEL-USER-2',
            mobile='5550112',
            user_type='user',
        )
        airline = Airlines.objects.create(code='CXA', name='Cancel Test Air')
        origin = Airport.objects.create(code='CX1', name='Origin Airport', city='Origin', country='India')
        dest = Airport.objects.create(code='CX2', name='Dest Airport', city='Dest', country='India')
        cls.future_flight = Flights.objects.create(
            code='CXFUTURE',
            airline=airline,
            from_airport=origin,
            to_airport=dest,
            departure=timezone.now() + timedelta(days=5),
            estimated_arrival=timezone.now() + timedelta(days=5, hours=2),
            business_class_slots=5,
            economy_slots=10,
            business_class_price=8000,
            economy_price=3000,
        )
        cls.past_flight = Flights.objects.create(
            code='CXPAST',
            airline=airline,
            from_airport=origin,
            to_airport=dest,
            departure=timezone.now() - timedelta(days=1),
            estimated_arrival=timezone.now() - timedelta(days=1, hours=-2),
            business_class_slots=5,
            economy_slots=10,
            business_class_price=8000,
            economy_price=3000,
        )
        cls.res_user1 = Reservation.objects.create(
            flight=cls.future_flight,
            user=cls.user1,
            type='2',
            seat_number='E1A',
            first_name='John',
            last_name='Doe',
            gender='Male',
            contact='5550111',
            email='john@example.com',
            status='0',
        )
        cls.res_user2 = Reservation.objects.create(
            flight=cls.future_flight,
            user=cls.user2,
            type='2',
            seat_number='E1B',
            first_name='Jane',
            last_name='Smith',
            gender='Female',
            contact='5550112',
            email='jane@example.com',
            status='0',
        )
        cls.res_past = Reservation.objects.create(
            flight=cls.past_flight,
            user=cls.user1,
            type='2',
            seat_number='E1C',
            first_name='John',
            last_name='Doe',
            gender='Male',
            contact='5550111',
            email='john@example.com',
            status='0',
        )

    def test_owner_can_cancel_pending_reservation(self):
        self.client.force_login(self.user1)
        response = self.client.post(
            reverse('cancel-reservation'),
            {'id': str(self.res_user1.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.res_user1.refresh_from_db()
        self.assertEqual(self.res_user1.status, '2')

    def test_user_cannot_cancel_other_users_reservation_idor_prevention(self):
        self.client.force_login(self.user1)
        response = self.client.post(
            reverse('cancel-reservation'),
            {'id': str(self.res_user2.id)},
        )
        self.assertEqual(response.status_code, 404)
        self.res_user2.refresh_from_db()
        self.assertEqual(self.res_user2.status, '0')

    def test_cannot_cancel_departed_flight_reservation(self):
        self.client.force_login(self.user1)
        response = self.client.post(
            reverse('cancel-reservation'),
            {'id': str(self.res_past.id)},
        )
        self.assertEqual(response.status_code, 409)
        self.res_past.refresh_from_db()
        self.assertEqual(self.res_past.status, '0')

    def test_cannot_cancel_already_cancelled_reservation(self):
        self.client.force_login(self.user1)
        self.res_user1.status = '2'
        self.res_user1.save()
        response = self.client.post(
            reverse('cancel-reservation'),
            {'id': str(self.res_user1.id)},
        )
        self.assertEqual(response.status_code, 409)


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

    def test_get_travel_response_handles_international_trip_budget(self):
        response = get_travel_response("My budget is ₹1,200,000 for 3 days. I want an international trip from Chennai.")
        self.assertIn("international", response.lower())
        self.assertTrue(any(city in response for city in [
            "Dubai", "Bangkok", "Singapore", "Bali", "Paris",
            "Colombo", "Kathmandu", "Kuala Lumpur",
        ]))
        personalized = get_travel_response(
            "International food and culture trip from Chennai in December, budget ₹1,200,000"
        )
        self.assertIn('Sample seasonal note for December', personalized)
        self.assertTrue(any(city in personalized for city in ('Bangkok', 'Kuala Lumpur')))

    def test_extract_travel_preferences_understands_destination_season_and_style(self):
        prefs = extract_travel_preferences(
            "Plan an international food and culture trip from Chennai to Bangkok in December"
        )
        self.assertEqual(prefs['origin'], 'Chennai')
        self.assertEqual(prefs['destination'], 'Bangkok')
        self.assertEqual(prefs['month'], 'December')
        self.assertIn('food experiences', prefs['preferences'])
        self.assertIn('culture and heritage', prefs['preferences'])

    def test_overseas_destination_implies_international_trip(self):
        prefs = extract_travel_preferences('Plan a 4 day trip from Chennai to Bangkok')
        self.assertEqual(prefs['trip_type'], 'international')
        self.assertEqual(prefs['destination'], 'Bangkok')

    def test_response_includes_verified_flight_inventory(self):
        flight = {
            'code': 'ARMS204',
            'from': 'MAA - Chennai',
            'to': 'BKK - Bangkok',
            'departure': '15 Dec 2026, 09:00 AM',
            'currency': 'INR',
            'economy_price': 24000,
            'economy_available': 12,
        }
        response = get_travel_response(
            'International trip from Chennai to Bangkok for 3 days in December',
            [flight],
        )
        self.assertIn('ARMS204', response)
        self.assertIn('INR 24000', response)
        self.assertIn('planning estimates, not booking quotes', response)

    def test_chatbot_answers_baggage_policy(self):
        response = get_travel_response("What is the baggage allowance?")
        self.assertIn("authoritative baggage-policy source", response)
        self.assertIn("official website", response)
        self.assertNotIn("7 kg", response)

    def test_chatbot_answers_cancellation_policy(self):
        response = get_travel_response("How can I cancel my booking?")
        self.assertIn("This only updates the ARMS record", response)
        self.assertIn("My Bookings", response)

    def test_chatbot_answers_check_in_timing(self):
        response = get_travel_response("What are the airport check-in times?")
        self.assertIn("does not have an authoritative check-in or boarding-time source", response)
        self.assertIn("official itinerary", response)

    def test_auto_provider_uses_matching_environment_key(self):
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'sk-or-test-key'}, clear=True):
            status = get_llm_provider_status(provider='auto')

        self.assertEqual(status, {
            'has_key': True,
            'provider': 'openrouter',
            'source': 'environment',
        })

    def test_model_handles_faq_with_conversation_context_and_requested_language(self):
        with (
            patch('armsApp.ai_chatbot._build_llm_grounding_context', return_value='Verified baggage policy facts.'),
            patch('armsApp.ai_chatbot.call_external_llm', return_value='Réponse personnalisée.') as llm_call,
        ):
            response = get_travel_response(
                'What is the baggage allowance?',
                language='fr',
                session_context=[
                    {'role': 'user', 'content': 'I am planning a trip to Paris.'},
                    {'role': 'assistant', 'content': 'How long will you stay?'},
                ],
                api_key='test-provider-key',
                ai_provider='openrouter',
            )

        self.assertEqual(response, 'Réponse personnalisée.')
        messages = llm_call.call_args.kwargs['messages']
        self.assertIn('Respond in French', messages[0]['content'])
        self.assertEqual(messages[1]['content'], 'I am planning a trip to Paris.')
        self.assertEqual(messages[-1]['content'], 'What is the baggage allowance?')

    def test_empty_flight_search_does_not_add_unfiltered_inventory_to_ai_context(self):
        with patch('armsApp.ai_chatbot.Flights.objects.filter') as flight_query:
            context = _build_llm_grounding_context([])

        flight_query.assert_not_called()
        self.assertIn('No matching scheduled flights', context)

    def test_extract_travel_preferences_for_kadapa_under_12000(self):
        prefs = extract_travel_preferences("plan a trip to Kadapa under₹12000")
        self.assertEqual(prefs['destination'], 'Kadapa')
        self.assertEqual(prefs['budget'], 12000)
        self.assertEqual(prefs['trip_type'], 'domestic')

    def test_kadapa_trip_response_matches_user_destination_and_budget(self):
        response = get_travel_response("plan a trip to Kadapa under₹12000")
        self.assertIn("Kadapa", response)
        self.assertIn("within the supplied budget", response)
        self.assertIn("Gandikota", response)
        self.assertIn("Belum Caves", response)
        self.assertNotIn("Singapore", response)
        self.assertNotIn("Istanbul", response)

    def test_compute_price_breakdown_percentages(self):
        from armsApp.ai_chatbot import compute_price_breakdown
        breakdown = compute_price_breakdown(10000.0)
        self.assertEqual(breakdown['base_fare'], 6800.0)
        self.assertEqual(breakdown['fuel_surcharge'], 1400.0)
        self.assertEqual(breakdown['airport_fee'], 1000.0)
        self.assertEqual(breakdown['gst'], 800.0)
        self.assertEqual(breakdown['total'], 10000.0)

    def test_price_chart_inquiry(self):
        response = get_travel_response("show fare breakdown price chart")
        self.assertIn("provide a flight code", response)


class TravelChatbotApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_chat_api_carries_trip_preferences_into_follow_up_turns(self):
        with (
            patch('armsApp.views.search_real_flights', return_value=[]),
            patch('armsApp.views.get_travel_response', return_value='Travel response') as response_mock,
        ):
            first = self.client.post(reverse('travel-chat-api'), {
                'message': 'Plan a 3-day trip to Tokyo under INR 50000',
            })
            follow_up = self.client.post(reverse('travel-chat-api'), {
                'message': 'Make it more cultural',
            })

        self.assertEqual(first.status_code, 200)
        self.assertEqual(follow_up.status_code, 200)
        carried_preferences = response_mock.call_args.kwargs['travel_preferences']
        self.assertEqual(carried_preferences['destination'], 'Tokyo')
        self.assertEqual(carried_preferences['budget'], 50000)
        self.assertEqual(carried_preferences['days'], 3)

    def test_clear_chat_removes_session_memory(self):
        session = self.client.session
        session['ai_chat_history'] = [{'role': 'user', 'content': 'Plan a trip'}]
        session['ai_travel_preferences'] = {'destination': 'Tokyo'}
        session.save()

        response = self.client.post(reverse('travel-chat-api'), {'action': 'clear_chat'})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('ai_chat_history', self.client.session)
        self.assertNotIn('ai_travel_preferences', self.client.session)

    def test_chat_api_rejects_oversized_messages(self):
        response = self.client.post(reverse('travel-chat-api'), {'message': 'x' * 2001})
        self.assertEqual(response.status_code, 400)

    def test_ai_settings_reject_unsupported_provider(self):
        response = self.client.post(reverse('travel-chat-api'), {
            'action': 'save_ai_settings',
            'provider': 'untrusted-provider',
        })
        self.assertEqual(response.status_code, 400)

    def test_ai_rate_limit_allows_thirty_requests_and_rejects_the_next(self):
        request = RequestFactory().post('/travel_chat_api')
        request.META['REMOTE_ADDR'] = '192.0.2.10'

        results = [_ai_chat_rate_limited(request) for _ in range(31)]

        self.assertEqual(results[:30], [False] * 30)
        self.assertTrue(results[30])


class TravelFlightSearchTests(TestCase):
    def test_international_search_matches_origin_and_excludes_domestic_routes(self):
        airline = Airlines.objects.create(code='TST', name='Test Air')
        chennai = Airport.objects.create(
            code='MAA', name='Chennai International Airport', city='Chennai', country='India'
        )
        bangkok = Airport.objects.create(
            code='BKK', name='Suvarnabhumi Airport', city='Bangkok', country='Thailand'
        )
        goa = Airport.objects.create(
            code='GOI', name='Goa International Airport', city='Goa', country='India'
        )
        departure = timezone.now() + timedelta(days=10)
        common = {
            'airline': airline,
            'from_airport': chennai,
            'departure': departure,
            'estimated_arrival': departure + timedelta(hours=4),
            'economy_slots': 10,
            'economy_price': 24000,
        }
        Flights.objects.create(code='INT204', to_airport=bangkok, **common)
        Flights.objects.create(code='DOM101', to_airport=goa, **common)

        matches = search_real_flights(
            extract_travel_preferences('International trip from Chennai')
        )

        self.assertEqual([flight['code'] for flight in matches], ['INT204'])
        self.assertEqual(matches[0]['currency'], 'INR')


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


class TwoFactorAuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='twofa_user',
            email='twofa@example.com',
            password='ComplexPassword123!',
            first_name='TwoFa',
            last_name='Tester'
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            custom_id='UID_2FA_01',
            mobile='5551234567',
            two_factor_enabled=True,
            user_type='user'
        )

    def test_otp_model_generation_and_verification(self):
        code = self.profile.generate_otp()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        self.assertIsNotNone(self.profile.otp_expiry)
        self.assertTrue(self.profile.otp_expiry > timezone.now())

        # Bad code fails
        wrong_code = '000000' if code != '000000' else '111111'
        self.assertFalse(self.profile.verify_otp(wrong_code))

        # Correct code succeeds and clears OTP
        self.assertTrue(self.profile.verify_otp(code))
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.otp_code)
        self.assertIsNone(self.profile.otp_expiry)

    def test_otp_expiry_check(self):
        code = self.profile.generate_otp()
        # Set expiry to past
        self.profile.otp_expiry = timezone.now() - timezone.timedelta(minutes=1)
        self.profile.save()
        self.assertFalse(self.profile.verify_otp(code))

    def test_login_requires_2fa_when_enabled(self):
        response = self.client.post(reverse('login-user'), {
            'username': 'twofa_user',
            'password': 'ComplexPassword123!'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), '2fa_required')
        self.assertEqual(data.get('redirect'), reverse('verify-2fa'))

        # User not yet authenticated in session
        self.assertNotIn('_auth_user_id', self.client.session)
        # Session has 2fa_user_id
        self.assertEqual(self.client.session.get('2fa_user_id'), self.user.id)

    def test_verify_2fa_view_success(self):
        code = self.profile.generate_otp()
        session = self.client.session
        session['2fa_user_id'] = self.user.id
        session.save()

        response = self.client.post(reverse('verify-2fa'), {'otp_code': code})
        self.assertRedirects(response, reverse('user-dashboard'))

        # User is now authenticated
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.id)
        self.assertNotIn('2fa_user_id', self.client.session)

    def test_verify_2fa_view_invalid_otp(self):
        self.profile.generate_otp()
        session = self.client.session
        session['2fa_user_id'] = self.user.id
        session.save()

        response = self.client.post(reverse('verify-2fa'), {'otp_code': '999999'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid or expired verification code")
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_verify_2fa_lockout_after_too_many_attempts(self):
        self.profile.generate_otp()
        session = self.client.session
        session['2fa_user_id'] = self.user.id
        session['2fa_attempts'] = 5
        session.save()

        # 6th attempt locks out
        response = self.client.post(reverse('verify-2fa'), {'otp_code': '000000'})
        self.assertRedirects(response, reverse('login-page'))
        self.assertNotIn('2fa_user_id', self.client.session)

    def test_toggle_2fa_endpoint(self):
        self.client.force_login(self.user)
        self.assertTrue(self.profile.two_factor_enabled)

        # Toggle off
        response = self.client.post(reverse('toggle-2fa'))
        self.assertRedirects(response, reverse('profile-page'))
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.two_factor_enabled)

        # Toggle on
        response = self.client.post(reverse('toggle-2fa'))
        self.assertRedirects(response, reverse('profile-page'))
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.two_factor_enabled)

    def test_resend_2fa_otp(self):
        self.profile.generate_otp()
        session = self.client.session
        session['2fa_user_id'] = self.user.id
        session.save()

        response = self.client.get(reverse('resend-2fa-otp'))
        self.assertRedirects(response, reverse('verify-2fa'))
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.otp_code)


class GuestReservationFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.airline = models.Airlines.objects.create(name='Global Airways')
        self.airport_a = models.Airport.objects.create(code='AAA', name='Alpha Airport')
        self.airport_b = models.Airport.objects.create(code='BBB', name='Beta Airport')
        self.aircraft = models.Aircraft.objects.create(
            code='AC01', model='Airbus A320', manufacturer='Airbus', business_capacity=4, economy_capacity=10
        )
        self.flight = models.Flights.objects.create(
            code='GL100',
            airline=self.airline,
            from_airport=self.airport_a,
            to_airport=self.airport_b,
            aircraft=self.aircraft,
            departure=timezone.now() + timezone.timedelta(days=2),
            estimated_arrival=timezone.now() + timezone.timedelta(days=2, hours=4),
            business_class_price=800,
            economy_price=200,
        )

    def test_guest_booking_success_and_reference_generation(self):
        session = self.client.session
        session['selected_flight'] = str(self.flight.id)
        session['selected_seats_data'] = json.dumps({
            'passenger_count': 1,
            'is_multi_passenger': True,
            'seats': [{'seat': 'E1A', 'type': '2', 'class': 'economy'}]
        })
        session.save()

        response = self.client.post(reverse('save-reservation'), {
            'flight': str(self.flight.id),
            'passenger_count': 1,
            'passenger_0_first_name': 'Jane',
            'passenger_0_last_name': 'Doe',
            'passenger_0_gender': 'Female',
            'passenger_0_seat': 'E1A',
            'passenger_0_type': '2',
            'email': 'jane.doe@example.com',
            'contact': '555-1234',
            'is_guest': '1',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.assertTrue(data.get('is_guest'))
        ref = data.get('booking_reference')
        self.assertIsNotNone(ref)
        self.assertTrue(ref.startswith('GUEST-'))

        res = models.Reservation.objects.get(booking_reference=ref)
        self.assertIsNone(res.user)
        self.assertTrue(res.is_guest)
        self.assertEqual(res.first_name, 'Jane')
        self.assertEqual(res.seat_number, 'E1A')

        conf_response = self.client.get(reverse('booking-confirmation', kwargs={'reference': ref}))
        self.assertEqual(conf_response.status_code, 200)
        self.assertContains(conf_response, ref)
        self.assertContains(conf_response, 'Jane')

    def test_guest_lookup_and_verification(self):
        res = models.Reservation.objects.create(
            flight=self.flight,
            user=None,
            is_guest=True,
            first_name='Alex',
            last_name='Morgan',
            gender='Female',
            email='alex.morgan@example.com',
            contact='555-9876',
            seat_number='E1B',
            type='2',
        )
        ref = res.booking_reference
        self.assertIsNotNone(ref)

        resp_email = self.client.post(reverse('guest-booking'), {
            'reference': ref,
            'verification': 'alex.morgan@example.com'
        })
        self.assertEqual(resp_email.status_code, 200)
        self.assertContains(resp_email, 'Alex Morgan')
        self.assertContains(resp_email, ref)

        resp_lname = self.client.post(reverse('guest-booking'), {
            'reference': ref,
            'verification': 'Morgan'
        })
        self.assertEqual(resp_lname.status_code, 200)
        self.assertContains(resp_lname, 'Alex Morgan')

        resp_fail = self.client.post(reverse('guest-booking'), {
            'reference': ref,
            'verification': 'wrong.person@example.com'
        })
        self.assertEqual(resp_fail.status_code, 200)
        self.assertContains(resp_fail, 'No reservation found matching')

    def test_guest_confirmation_requires_recent_session_authorization(self):
        reservation = models.Reservation.objects.create(
            flight=self.flight,
            user=None,
            is_guest=True,
            first_name='Taylor',
            last_name='Guest',
            gender='Female',
            email='taylor.guest@example.com',
            contact='555-1111',
            seat_number='E1A',
            type='2',
        )
        confirmation_url = reverse(
            'booking-confirmation',
            kwargs={'reference': reservation.booking_reference},
        )

        unauthorized = self.client.get(confirmation_url)
        self.assertRedirects(unauthorized, reverse('guest-booking'))

        verified = self.client.post(reverse('guest-booking'), {
            'reference': reservation.booking_reference,
            'verification': reservation.email,
        })
        self.assertEqual(verified.status_code, 200)
        authorized = self.client.get(confirmation_url)
        self.assertEqual(authorized.status_code, 200)
        self.assertContains(authorized, 'Taylor Guest')

    def test_guest_cancellation_attempts_are_rate_limited_by_ip(self):
        responses = [
            self.client.post(reverse('cancel-guest-reservation'), {})
            for _ in range(6)
        ]

        self.assertEqual([response.status_code for response in responses[:5]], [400] * 5)
        self.assertEqual(responses[5].status_code, 429)

    def test_cancel_guest_reservation(self):
        res = models.Reservation.objects.create(
            flight=self.flight,
            user=None,
            is_guest=True,
            first_name='Robert',
            last_name='Paulson',
            gender='Male',
            email='robert@example.com',
            contact='555-4321',
            seat_number='E1C',
            type='2',
            status='0',
        )
        ref = res.booking_reference

        resp_fail = self.client.post(reverse('cancel-guest-reservation'), {
            'reference': ref,
            'verification': 'hacker@example.com'
        })
        self.assertEqual(resp_fail.status_code, 403)

        resp_success = self.client.post(reverse('cancel-guest-reservation'), {
            'reference': ref,
            'verification': 'robert@example.com'
        })
        self.assertEqual(resp_success.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.status, '2')


class LegalPagesTests(SimpleTestCase):
    def test_terms_of_service_page(self):
        response = self.client.get(reverse('terms'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Terms of Service")
        self.assertContains(response, "ARMS 2.0")

    def test_privacy_policy_page(self):
        response = self.client.get(reverse('privacy'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy Policy")
        self.assertContains(response, "Data Minimization")


class UserTravelPreferencesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='globetrotter',
            email='globe@example.com',
            password='Password123!'
        )

    def test_update_travel_preferences(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('update-travel-preferences'), {
            'preferred_language': 'es',
            'preferred_currency': 'EUR',
            'preferred_seat_class': 'Business',
            'dietary_preference': 'Vegetarian',
            'interests': 'art, architecture',
            'budget_level': 'luxury',
        })
        self.assertRedirects(response, reverse('profile-page'))
        pref = self.user.travel_preference
        self.assertEqual(pref.preferred_language, 'es')
        self.assertEqual(pref.preferred_currency, 'EUR')
        self.assertEqual(pref.preferred_seat_class, 'Business')
        self.assertEqual(pref.dietary_preference, 'Vegetarian')


class MultilingualAndToolChatbotTests(TestCase):
    def setUp(self):
        self.airline = models.Airlines.objects.create(name='Skyline Air')
        self.airport_a = models.Airport.objects.create(code='MAA', name='Chennai')
        self.airport_b = models.Airport.objects.create(code='DXB', name='Dubai')
        self.aircraft = models.Aircraft.objects.create(
            code='AC99', model='Boeing 737', manufacturer='Boeing', business_capacity=2, economy_capacity=5
        )
        self.flight = models.Flights.objects.create(
            code='SK101',
            airline=self.airline,
            from_airport=self.airport_a,
            to_airport=self.airport_b,
            aircraft=self.aircraft,
            departure=timezone.now() + timezone.timedelta(days=1),
            estimated_arrival=timezone.now() + timezone.timedelta(days=1, hours=4),
            business_class_price=600,
            economy_price=250,
        )

    def test_multilingual_spanish_faq(self):
        response = get_travel_response("¿Cuál es la política de equipaje?", language='es')
        self.assertIn("fuente oficial de equipaje", response)
        self.assertNotIn("7 kg", response)

    def test_execute_travel_tool_search_flights(self):
        from armsApp.ai_chatbot import execute_travel_tool
        result = execute_travel_tool('search_flights', {'origin': 'Chennai', 'destination': 'Dubai'})
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0]['code'], 'SK101')

    def test_execute_travel_tool_flight_details(self):
        from armsApp.ai_chatbot import execute_travel_tool
        result = execute_travel_tool('get_flight_details', {'code': 'SK101'})
        self.assertIsInstance(result, dict)
        self.assertEqual(result['code'], 'SK101')
        self.assertEqual(result['airline'], 'Skyline Air')

    def test_guest_reservation_tool_requires_both_passenger_verifiers(self):
        from armsApp.ai_chatbot import execute_travel_tool

        reservation = Reservation.objects.create(
            flight=self.flight,
            user=None,
            is_guest=True,
            first_name='Alex',
            last_name='Morgan',
            gender='Female',
            email='alex.morgan@example.com',
            contact='555-9876',
            seat_number='E1B',
            type='2',
        )

        missing_verifier = execute_travel_tool('lookup_reservation', {
            'reference': reservation.booking_reference,
            'email': 'alex.morgan@example.com',
        })
        verified = execute_travel_tool('lookup_reservation', {
            'reference': reservation.booking_reference,
            'email': 'alex.morgan@example.com',
            'last_name': 'Morgan',
        })

        self.assertIn('error', missing_verifier)
        self.assertEqual(verified['reference'], reservation.booking_reference)

    def test_execute_travel_tool_rejects_invalid_arguments(self):
        from armsApp.ai_chatbot import execute_travel_tool

        self.assertIn('error', execute_travel_tool('search_flights', []))
        self.assertIn(
            'positive finite number',
            execute_travel_tool('search_flights', {'max_price': float('nan')})['error'],
        )
        self.assertIn(
            'unsupported fields',
            execute_travel_tool('search_flights', {'origin': 'Chennai', 'delete_all': True})['error'],
        )

    def test_unknown_destination_does_not_receive_synthetic_prices_or_routes(self):
        from armsApp.ai_chatbot import _build_local_recommendations

        self.assertEqual(
            _build_local_recommendations({
                'destination': 'Atlantis',
                'trip_type': 'international',
                'days': 3,
            }),
            [],
        )
        response = get_travel_response('Plan a trip to Atlantis')
        self.assertIn('do not have a verified destination guide', response)
        self.assertNotIn('nearest hub', response.lower())

    def test_price_lookup_does_not_substitute_an_unrequested_flight(self):
        response = get_travel_response('price chart for flight ZX999')
        self.assertIn('No matching flight fare is recorded', response)
        self.assertNotIn('SK101', response)

    def test_ai_tool_call_is_executed_and_followed_by_a_grounded_completion(self):
        from armsApp.ai_chatbot import call_external_llm

        tool_response = Mock(status_code=200)
        tool_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': None,
                    'tool_calls': [{
                        'id': 'call_flights_1',
                        'type': 'function',
                        'function': {
                            'name': 'search_flights',
                            'arguments': json.dumps({'origin': 'Chennai', 'destination': 'Dubai'}),
                        },
                    }],
                },
            }],
        }
        final_response = Mock(status_code=200)
        final_response.json.return_value = {
            'choices': [{'message': {'content': 'ARMS lists flight SK101.'}}],
        }

        with patch('armsApp.ai_chatbot.requests.post', side_effect=[tool_response, final_response]) as request:
            result = call_external_llm(
                [{'role': 'user', 'content': 'Find a flight from Chennai to Dubai.'}],
                api_key='sk-or-test-key',
                provider='openrouter',
            )

        self.assertEqual(result, 'ARMS lists flight SK101.')
        self.assertEqual(request.call_count, 2)
        first_payload = request.call_args_list[0].kwargs['json']
        tool_names = {tool['function']['name'] for tool in first_payload['tools']}
        self.assertEqual(
            tool_names,
            {'search_flights', 'get_flight_details', 'get_price_chart'},
        )
        final_messages = request.call_args_list[1].kwargs['json']['messages']
        self.assertTrue(any(message.get('role') == 'tool' and 'SK101' in message['content'] for message in final_messages))
        self.assertNotIn('tools', request.call_args_list[1].kwargs['json'])

    def test_chat_booking_reference_is_routed_to_verified_portal(self):
        with patch('armsApp.ai_chatbot.call_external_llm') as model_call:
            response = get_travel_response(
                'Please look up GUEST-AB12-CD34',
                api_key='sk-or-test-key',
                ai_provider='openrouter',
            )

        self.assertIn('Guest Booking Lookup', response)
        model_call.assert_not_called()

    def test_chatbot_greeting_response_does_not_default_to_goa(self):
        response = get_travel_response("Hello")
        self.assertIn("Welcome to", response)
        self.assertNotIn("Suggested Goa itinerary", response)

    def test_chatbot_destination_specific_guide(self):
        tokyo_resp = get_travel_response("Tell me about Tokyo")
        self.assertIn("Tokyo", tokyo_resp)
        self.assertIn("Shibuya", tokyo_resp)
        self.assertNotIn("bookable flights", tokyo_resp.lower())

        paris_resp = get_travel_response("Trip to Paris")
        self.assertIn("Paris", paris_resp)
        self.assertIn("Eiffel Tower", paris_resp)

    def test_ai_settings_api_actions(self):
        client = Client()
        # Test save settings
        save_resp = client.post(reverse('travel-chat-api'), {
            'action': 'save_ai_settings',
            'api_key': 'sk-or-v1-testkey123456789',
            'provider': 'openrouter',
            'model': 'meta-llama/llama-3.3-70b-instruct:free',
        })
        self.assertEqual(save_resp.status_code, 200)
        self.assertEqual(save_resp.json()['status'], 'success')

        # Test get status
        status_resp = client.post(reverse('travel-chat-api'), {
            'action': 'get_ai_status',
        })
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        self.assertTrue(status_data['has_key'])
        self.assertEqual(status_data['provider'], 'openrouter')
