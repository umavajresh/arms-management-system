from django.db import models
from django.utils import timezone
from datetime import timedelta, datetime
from armsApp.models import Airlines, Airport, Aircraft, Flights

class FlightSchedule(models.Model):
    """
    Model for recurring flight schedules. Each FlightSchedule can generate
    multiple Flight instances based on recurrence pattern.
    """
    RECURRENCE_CHOICES = (
        ('daily', 'Daily'),
        ('weekdays', 'Weekdays (Mon-Fri)'),
        ('weekends', 'Weekends (Sat-Sun)'),
        ('weekly', 'Weekly'),
        ('custom', 'Custom Pattern')
    )
    
    # Basic flight info
    code = models.CharField(max_length=20)
    airline = models.ForeignKey(Airlines, on_delete=models.CASCADE)
    from_airport = models.ForeignKey(Airport, on_delete=models.CASCADE, related_name="scheduled_departures")
    to_airport = models.ForeignKey(Airport, on_delete=models.CASCADE, related_name="scheduled_arrivals")
    aircraft = models.ForeignKey(Aircraft, on_delete=models.CASCADE)
    
    # Schedule information
    departure_time = models.TimeField(help_text="Local departure time")
    arrival_time = models.TimeField(help_text="Local arrival time")
    duration_minutes = models.IntegerField(help_text="Flight duration in minutes")
    
    # Recurrence pattern
    recurrence_pattern = models.CharField(max_length=20, choices=RECURRENCE_CHOICES, default='daily')
    days_of_week = models.CharField(max_length=20, blank=True, 
                                   help_text="Days of week as comma-separated integers (0=Mon, 6=Sun)")
    
    # Price information
    business_class_price = models.FloatField(default=0)
    economy_price = models.FloatField(default=0)
    
    # Schedule validity period
    start_date = models.DateField()
    end_date = models.DateField()
    
    # Status
    is_active = models.BooleanField(default=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.code}: {self.from_airport.code} to {self.to_airport.code} ({self.recurrence_pattern})"
    
    def get_days_list(self):
        """Convert days_of_week string to list of integers"""
        if not self.days_of_week:
            return []
        return [int(day) for day in self.days_of_week.split(',')]
    
    def should_run_on_date(self, date):
        """Check if flight should operate on the given date"""
        # Check if date is within validity period
        if date < self.start_date or date > self.end_date:
            return False
            
        # Check recurrence pattern
        weekday = date.weekday()  # 0=Monday, 6=Sunday
        
        if self.recurrence_pattern == 'daily':
            return True
        elif self.recurrence_pattern == 'weekdays':
            return 0 <= weekday <= 4  # Monday to Friday
        elif self.recurrence_pattern == 'weekends':
            return weekday >= 5  # Saturday and Sunday
        elif self.recurrence_pattern == 'weekly':
            return weekday == self.get_days_list()[0] if self.get_days_list() else False
        elif self.recurrence_pattern == 'custom':
            return weekday in self.get_days_list()
        
        return False
    
    def generate_flights_for_date_range(self, start_date, end_date):
        """Generate flight instances for the given date range"""
        flights_created = 0
        current_date = start_date
        
        while current_date <= end_date:
            if self.should_run_on_date(current_date):
                # Create departure datetime
                departure_datetime = datetime.combine(
                    current_date, 
                    self.departure_time,
                    tzinfo=timezone.get_current_timezone()
                )
                
                # Calculate arrival datetime (might be next day)
                arrival_datetime = departure_datetime + timedelta(minutes=self.duration_minutes)
                
                # Create flight instance
                flight = Flights(
                    code=f"{self.code}-{current_date.strftime('%Y%m%d')}",
                    airline=self.airline,
                    from_airport=self.from_airport,
                    to_airport=self.to_airport,
                    aircraft=self.aircraft,
                    departure=departure_datetime,
                    estimated_arrival=arrival_datetime,
                    business_class_price=self.business_class_price,
                    economy_price=self.economy_price,
                    business_class_slots=self.aircraft.business_capacity,
                    economy_slots=self.aircraft.economy_capacity,
                    delete_flag=0
                )
                
                # Save only if this flight doesn't exist yet
                if not Flights.objects.filter(
                    code=flight.code,
                    airline=flight.airline,
                    from_airport=flight.from_airport,
                    to_airport=flight.to_airport,
                    departure=flight.departure
                ).exists():
                    flight.save()
                    flights_created += 1
            
            current_date += timedelta(days=1)
        
        return flights_created
        
    def generate_upcoming_flights(self, days_ahead=30):
        """Generate flights for the upcoming days"""
        today = timezone.now().date()
        end_date = today + timedelta(days=days_ahead)
        end_date = min(end_date, self.end_date)  # Don't go beyond schedule end date
        
        return self.generate_flights_for_date_range(today, end_date)
