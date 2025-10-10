from django.contrib import admin
from django.urls import path
from armsApp import models
from armsApp.admin_views import UpcomingFlightsAdminView, ReservationApprovalAdminView

# Customize admin site
class CustomAdminSite(admin.AdminSite):
    site_header = "Airline Reservation Management System"
    site_title = "ARMS Admin"
    index_title = "ARMS Administration"
    
    def get_urls(self):
        urls = super().get_urls()
        
        # Initialize admin views
        upcoming_flights_view = UpcomingFlightsAdminView(self)
        reservation_approval_view = ReservationApprovalAdminView(self)
        
        custom_urls = [
            path('upcoming-flights/', self.admin_view(upcoming_flights_view.upcoming_flights_view), name='upcoming-flights'),
        ] + reservation_approval_view.get_urls()
        
        return custom_urls + urls

# Use the custom admin site
admin_site = CustomAdminSite(name='admin')

# Register your models here.
class AirlinesAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'country', 'status')
    list_filter = ('status',)
    search_fields = ('code', 'name', 'country')

class AirportAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'city', 'country', 'status')
    list_filter = ('status', 'country')
    search_fields = ('code', 'name', 'city', 'country')

class FlightsAdmin(admin.ModelAdmin):
    list_display = ('code', 'airline', 'from_airport', 'to_airport', 'departure', 'estimated_arrival')
    list_filter = ('airline', 'from_airport', 'to_airport')
    search_fields = ('code', 'airline__name', 'from_airport__name', 'to_airport__name')
    date_hierarchy = 'departure'
    
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_upcoming_flights_link'] = True
        return super().changelist_view(request, extra_context=extra_context)

class AircraftAdmin(admin.ModelAdmin):
    list_display = ('code', 'model', 'business_capacity', 'economy_capacity', 'status')
    list_filter = ('status',)
    search_fields = ('code', 'model')

class ReservationAdmin(admin.ModelAdmin):
    list_display = ('get_reservation_code', 'user', 'flight', 'seat_type_display', 'status_display')
    list_filter = ('status', 'type')
    search_fields = ('flight__code', 'user__username', 'first_name', 'last_name')
    
    def get_reservation_code(self, obj):
        return f"RES-{obj.id:08d}"
    get_reservation_code.short_description = "Reservation Code"
    
    def seat_type_display(self, obj):
        return "Business Class" if obj.type == '1' else "Economy Class"
    seat_type_display.short_description = "Seat Type"
    
    def status_display(self, obj):
        status_text, status_class = obj.get_status_display_text()
        return status_text
    status_display.short_description = "Status"
    
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_reservation_approval_link'] = True
        return super().changelist_view(request, extra_context=extra_context)

# Register models with our custom admin site
admin_site.register(models.Airlines, AirlinesAdmin)
admin_site.register(models.Airport, AirportAdmin)
admin_site.register(models.Flights, FlightsAdmin)
admin_site.register(models.Aircraft, AircraftAdmin)
admin_site.register(models.Reservation, ReservationAdmin)

class FlightScheduleAdmin(admin.ModelAdmin):
    list_display = ('code', 'airline', 'from_airport', 'to_airport', 'recurrence_pattern', 
                   'start_date', 'end_date', 'is_active')
    list_filter = ('airline', 'recurrence_pattern', 'is_active')
    search_fields = ('code', 'airline__name', 'from_airport__name', 'to_airport__name')
    date_hierarchy = 'start_date'
    actions = ['generate_flights_for_30_days', 'activate_schedules', 'deactivate_schedules']
    
    fieldsets = (
        ('Flight Information', {
            'fields': ('code', 'airline', 'from_airport', 'to_airport', 'aircraft')
        }),
        ('Schedule', {
            'fields': ('departure_time', 'arrival_time', 'duration_minutes')
        }),
        ('Recurrence', {
            'fields': ('recurrence_pattern', 'days_of_week', 'start_date', 'end_date')
        }),
        ('Pricing', {
            'fields': ('business_class_price', 'economy_price')
        }),
        ('Status', {
            'fields': ('is_active', 'delete_flag')
        }),
    )
    
    def generate_flights_for_30_days(self, request, queryset):
        flights_count = 0
        for schedule in queryset:
            flights_count += schedule.generate_upcoming_flights(days_ahead=30)
        self.message_user(request, f"Generated {flights_count} flights for {queryset.count()} schedules.")
    generate_flights_for_30_days.short_description = "Generate flights for the next 30 days"
    
    def activate_schedules(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} schedules have been activated.")
    activate_schedules.short_description = "Activate selected schedules"
    
    def deactivate_schedules(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} schedules have been deactivated.")
    deactivate_schedules.short_description = "Deactivate selected schedules"

# Register with our custom admin site
admin_site.register(models.FlightSchedule, FlightScheduleAdmin)

# Override the default admin site
admin.site = admin_site
