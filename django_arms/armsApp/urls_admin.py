from django.urls import path
from armsApp.admin_views import UpcomingFlightsAdminView

# This is needed for custom admin views
app_name = 'armsApp'

# Create the custom admin views
upcoming_flights_view = UpcomingFlightsAdminView(None)  # Will be properly set during get_urls

# Add custom URLs
urlpatterns = [
    # Custom admin views
]
