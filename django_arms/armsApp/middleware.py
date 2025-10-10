from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve

class UserProfileMiddleware(MiddlewareMixin):
    """
    Middleware to ensure users have a UserProfile and are redirected correctly.
    Also enforces separation between admin and regular user interfaces.
    """
    
    # Admin-only URLs
    ADMIN_URLS = [
        'home-page', 'airline-page', 'airport-page', 'flight-page', 'reservation',
        'manage-airline', 'manage-airport', 'manage-flight', 'view-flight-pk',
        'save-airline', 'save-airport', 'save-flight',
        'delete-airline-pk', 'delete-airport-pk', 'delete-flight-pk',
        'view-reservation-pk', 'delete-reservation-pk', 'update-reservation'
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
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Skip middleware for anonymous users or login/registration URLs
        if not request.user.is_authenticated or 'login' in request.path or 'register' in request.path:
            return None
            
        # Skip for Django admin URLs
        if request.path.startswith('/admin/'):
            return None
            
        # Skip for static files
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return None
        
        # Try to get the current URL name
        try:
            url_name = resolve(request.path_info).url_name
        except:
            url_name = None
            
        # Check if user has a profile
        try:
            profile = request.user.profile
            # Both is_admin flag and user_type are available, but we prefer using user_type
            
            # If admin tries to access user-only pages
            if profile.user_type == 'admin' and url_name in self.USER_URLS:
                messages.warning(request, "That page is for regular users only. Redirected to admin dashboard.")
                return redirect('home-page')
                
            # If regular user tries to access admin-only pages
            if profile.user_type == 'user' and url_name in self.ADMIN_URLS:
                messages.warning(request, "That page requires administrative privileges. Redirected to user dashboard.")
                return redirect('user-dashboard')
                
        except Exception:
            # Create a default profile if none exists
            from armsApp.models import UserProfile
            try:
                profile = UserProfile.objects.create(
                    user=request.user,
                    custom_id=f"UID{request.user.id}",
                    mobile="",
                    is_admin=False,
                    user_type='user'  # Default to regular user
                )
                # New users should be directed to the user dashboard
                if url_name in self.ADMIN_URLS:
                    messages.info(request, "Your account has been set up as a regular user.")
                    return redirect('user-dashboard')
            except Exception as e:
                messages.error(request, f"Error creating user profile: {str(e)}")
                
        return None
