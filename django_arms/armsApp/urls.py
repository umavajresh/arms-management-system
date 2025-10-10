from django.contrib import admin
from django.urls import path,include
from . import views
from . import views_password_reset
from .views_additions import upcoming_flights
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('',views.landing_page, name='public-page'),
    path('search_flight',views.search_flight, name='search-flight'),
    path('search_result',views.search_result, name="search-result"),
    path('search_result/<int:fromA>/<int:toA>/<str:departure>',views.search_result, name="search-result-with-params"),
    path('reserve_form/<int:pk>',views.reserve_form,name='reserve-form'),
    path('save_reservation',views.save_reservation,name='save-reservation'),
    path('home',views.home, name="home-page"),
    path('login',views.login_page,name='login-page'),
    path('register',views.userregister,name='register-page'),
    path('save_register',views.save_register,name='register-user'),
    path('user_login',views.login_user,name='login-user'),
    path('home',views.home,name='home-page'),
    path('logout',views.logout_user,name='logout'),
    path('profile',views.profile,name='profile-page'),
    path('update_password',views.update_password,name='update-password'),
    path('update_profile',views.update_profile,name='update-profile'),
    path('airline',views.list_airline,name='airline-page'),
    path('manage_airline',views.manage_airline,name='manage-airline'),
    path('manage_airline/<int:pk>',views.manage_airline,name='manage-airline-pk'),
    path('save_airline',views.save_airline,name='save-airline'),
    path('delete_airline/<int:pk>',views.delete_airline,name='delete-airline-pk'),
    path('airport',views.list_airport,name='airport-page'),
    path('manage_airport',views.manage_airport,name='manage-airport'),
    path('manage_airport/<int:pk>',views.manage_airport,name='manage-airport-pk'),
    path('save_airport',views.save_airport,name='save-airport'),
    path('delete_airport/<int:pk>',views.delete_airport,name='delete-airport-pk'),
    path('flight',views.list_flight,name='flight-page'),
    path('manage_flight',views.manage_flight,name='manage-flight'),
    path('manage_flight/<int:pk>',views.manage_flight,name='manage-flight-pk'),
    path('view_flight/<int:pk>',views.view_flight,name='view-flight-pk'),
    path('save_flight',views.save_flight,name='save-flight'),
    path('delete_flight/<int:pk>',views.delete_flight,name='delete-flight-pk'),
    path('reservation',views.list_reservation,name='reservation'),
    path('view_reservation/<int:pk>',views.view_reservation,name='view-reservation-pk'),
    path('delete_reservation/<int:pk>',views.delete_reservation,name='delete-reservation-pk'),
    path('update_reservation',views.update_reservation,name='update-reservation'),
    path('user_dashboard',views.user_dashboard,name='user-dashboard'),
    path('user_reservations',views.user_reservations,name='user-reservations'),
    path('cancel_reservation',views.cancel_reservation,name='cancel-reservation'),
    path('upcoming_flights',upcoming_flights,name='upcoming-flights'),
    path('seat_selection/<int:pk>',views.seat_selection,name='seat-selection'),
    path('aircraft',views.aircraft,name='aircraft-page'),
    path('manage_aircraft',views.manage_aircraft,name='manage-aircraft'),
    path('manage_aircraft/<int:pk>',views.manage_aircraft,name='manage-aircraft-pk'),
    path('save_aircraft',views.save_aircraft,name='save-aircraft'),
    path('delete_aircraft/<int:pk>',views.delete_aircraft,name='delete-aircraft-pk'),
    
    # Verification URLs
    path('get_captcha',views.get_captcha,name='get-captcha'),
    path('verify_reservation',views.verify_reservation,name='verify-reservation'),
    
    # Notification URLs
    path('mark_notification_read',views.mark_notification_read,name='mark-notification-read'),
    
    # Password reset URLs
    path('forgot-password/', views_password_reset.forgot_password, name='forgot-password'),
    path('verify-identity/', views_password_reset.verify_identity, name='verify-identity'),
    path('reset-password/', views_password_reset.reset_password, name='reset-password'),
    path('answer-security-question/', views_password_reset.verify_identity, name='answer-security-question'),
]+ static(settings.MEDIA_URL, document_root = settings.MEDIA_ROOT)
