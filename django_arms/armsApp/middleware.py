from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.urls import Resolver404, resolve
from django.http import HttpResponseServerError
import logging

logger = logging.getLogger(__name__)

class UserProfileMiddleware(MiddlewareMixin):
    """
    Middleware to ensure users have a UserProfile and are redirected correctly.
    Also enforces separation between admin and regular user interfaces.
    """
    
    # Admin-only URLs
    ADMIN_URLS = [
        'home-page', 'airline-page', 'airport-page', 'flight-page', 'reservation',
        'manage-airline', 'manage-airline-pk', 'manage-airport', 'manage-airport-pk',
        'manage-flight', 'manage-flight-pk', 'view-flight-pk',
        'save-airline', 'save-airport', 'save-flight',
        'delete-airline-pk', 'delete-airport-pk', 'delete-flight-pk',
        'view-reservation-pk', 'delete-reservation-pk', 'update-reservation',
        'aircraft-page', 'manage-aircraft', 'manage-aircraft-pk',
        'save-aircraft', 'delete-aircraft-pk',
    ]
    
    # User-only URLs
    USER_URLS = [
        'user-dashboard', 'user-reservations', 'cancel-reservation',
        'search-flight', 'search-result', 'reserve-form', 'save-reservation',
        'seat-selection'
    ]
    
    # Common URLs that both user types can access
    COMMON_URLS = [
        'public-page', 'profile-page', 'update-password', 'update-profile',
        'logout'
    ]
    PROTECTED_URLS = ADMIN_URLS + [
        name for name in USER_URLS if name != 'save-reservation'
    ] + [name for name in COMMON_URLS if name != 'public-page']
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.path.startswith(('/admin/', '/static/', '/media/')):
            return None

        try:
            url_name = resolve(request.path_info).url_name
        except Resolver404:
            return None

        if not request.user.is_authenticated:
            if url_name in self.PROTECTED_URLS:
                return redirect_to_login(request.get_full_path())
            return None

        # Check if user has a profile
        from armsApp.models import UserProfile

        try:
            profile = request.user.profile
        except UserProfile.DoesNotExist:
            try:
                profile = UserProfile.objects.create(
                    user=request.user,
                    custom_id=f"UID{request.user.id}",
                    mobile="",
                    is_admin=False,
                    user_type='user'  # Default to regular user
                )
                if url_name in self.ADMIN_URLS:
                    messages.info(request, "Your account has been set up as a regular user.")
                    return redirect('user-dashboard')
            except Exception as e:
                logger.exception("Unable to create a profile for authenticated user %s", request.user.pk)
                return HttpResponseServerError("Your account could not be verified. Please try again.")
        except Exception:
            logger.exception("Unable to load profile for authenticated user %s", request.user.pk)
            return HttpResponseServerError("Your account could not be verified. Please try again.")

        if profile.user_type not in {'admin', 'user'}:
            logger.error(
                "Invalid user profile role for authenticated user %s",
                request.user.pk,
            )
            return HttpResponseServerError("Your account could not be verified. Please contact support.")

        if profile.user_type == 'admin' and url_name in self.USER_URLS:
            messages.warning(request, "That page is for regular users only. Redirected to admin dashboard.")
            return redirect('home-page')

        if profile.user_type == 'user' and url_name in self.ADMIN_URLS:
            messages.warning(request, "That page requires administrative privileges. Redirected to user dashboard.")
            return redirect('user-dashboard')
                
        return None
