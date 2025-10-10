from email.policy import default
from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
import qrcode
from PIL import Image
from django.contrib.auth.models import User
from datetime import timedelta, datetime


# Create your models here.
class Airlines(models.Model):
    code = models.CharField(max_length=5, unique=True)
    name = models.CharField(max_length=250)
    country = models.CharField(max_length=100, blank=True, null=True)
    image_path = models.ImageField(upload_to='airlines', blank=True, null=True)
    status = models.CharField(max_length=2, choices=(('1','Active'), ('2','Inactive')), default = 1)
    delete_flag = models.IntegerField(default = 0)
    date_added = models.DateTimeField(default = timezone.now)
    date_created = models.DateTimeField(auto_now = True)

    class Meta:
        verbose_name_plural = "List of Airlines"

    def __str__(self):
        return str(f"{self.code} - {self.name}")


    def save(self, *args, **kwargs):
        super(Airlines, self).save(*args, **kwargs)
        print(self.image_path)
        if not self.image_path == '':
            imag = Image.open(self.image_path.path)
            width = imag.width
            height = imag.height
            if imag.width > 640:
                perc = (width - 640) / width
                width = 640
                height = height - (height * perc)
            if imag.height > 480:
                perc = (height - 480) / height
                height = 480
                width = width - (width * perc)
            output_size = (width, height)
            imag.thumbnail(output_size)
            imag.save(self.image_path.path)

    def delete(self, *args, **kwargs):
        super(Airlines, self).delete(*args, **kwargs)
        storage, path = self.image_path.storage, self.image_path.path
        storage.delete(path)
        
class Airport(models.Model):
    code = models.CharField(max_length=5, unique=True)
    name = models.CharField(max_length=250)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=2, choices=(('1','Active'), ('2','Inactive')), default = 1)
    delete_flag = models.IntegerField(default = 0)
    date_added = models.DateTimeField(default = timezone.now)
    date_created = models.DateTimeField(auto_now = True)

    class Meta:
        verbose_name_plural = "List of Airports"

    def __str__(self):
        return str(f"{self.code} - {self.name}")

class Aircraft(models.Model):
    code = models.CharField(max_length=5, unique=True)
    model = models.CharField(max_length=250)
    manufacturer = models.CharField(max_length=100)
    business_capacity = models.IntegerField(default=0)
    economy_capacity = models.IntegerField(default=0)
    status = models.CharField(max_length=2, choices=(('1','Active'), ('2','Inactive')), default = 1)
    delete_flag = models.IntegerField(default = 0)
    date_added = models.DateTimeField(default = timezone.now)
    date_created = models.DateTimeField(auto_now = True)

    class Meta:
        verbose_name_plural = "List of Aircraft"

    def __str__(self):
        return str(f"{self.code} - {self.model}")

class Flights(models.Model):
    code = models.CharField(max_length=250)
    airline = models.ForeignKey(Airlines, on_delete=models.CASCADE)
    from_airport = models.ForeignKey(Airport, on_delete=models.CASCADE, related_name="From_Airport")
    to_airport = models.ForeignKey(Airport, on_delete=models.CASCADE, related_name="To_Airport")
    aircraft = models.ForeignKey(Aircraft, on_delete=models.CASCADE, default=None, null=True)
    departure = models.DateTimeField()
    estimated_arrival = models.DateTimeField()
    business_class_slots = models.IntegerField(default=0)
    economy_slots = models.IntegerField(default=0)
    business_class_price = models.FloatField(default=0)
    economy_price = models.FloatField(default=0)
    currency = models.CharField(max_length=3, default="INR", help_text="Currency code (INR for Indian Rupees)")
    delete_flag = models.IntegerField(default = 0)
    date_added = models.DateTimeField(default = timezone.now)
    date_created = models.DateTimeField(auto_now = True)
    
    def save(self, *args, **kwargs):
        # Update slots based on aircraft capacity when saving
        if self.aircraft:
            self.business_class_slots = self.aircraft.business_capacity
            self.economy_slots = self.aircraft.economy_capacity
        super(Flights, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "List of Flights"

    def __str__(self):
        return str(f"{self.code} [{self.from_airport.name} - {self.to_airport.name}]")
    
    def is_bookable(self):
        """
        Check if this flight is still bookable (hasn't departed yet)
        """
        from django.utils import timezone
        current_time = timezone.now()
        return self.departure > current_time
    
    def get_booking_status(self):
        """
        Get a user-friendly message about booking availability
        """
        if not self.is_bookable():
            return "Flight has departed"
        return "Available for booking"

    def b_slot(self):
        try:
            reservation = Reservation.objects.exclude(status = 2).filter(flight=self, type = 1).count()
            if reservation is None:
                reservation = 0

        except:
            reservation = 0

        return self.business_class_slots - reservation

    def e_slot(self):
        try:
            reservation = Reservation.objects.exclude(status = 2).filter(flight=self, type = 2).count()
            if reservation is None:
                reservation = 0

        except:
            reservation = 0
        return self.economy_slots - reservation
    
    @property
    def booked_business(self):
        try:
            # Only count approved reservations
            return Reservation.objects.filter(flight=self, type=1, status='1').count() or 0
        except:
            return 0
    
    @property
    def booked_economy(self):
        try:
            # Only count approved reservations  
            return Reservation.objects.filter(flight=self, type=2, status='1').count() or 0
        except:
            return 0

        
# New model for custom user profiles 
class UserProfile(models.Model):
    USER_TYPE_CHOICES = [
        ('admin', 'Administrator'),
        ('user', 'Regular User'),
    ]
    
    SECURITY_QUESTION_CHOICES = [
        ('nickname', 'What is your nickname?'),
        ('pet', 'What is your pet\'s name?'),
        ('birthplace', 'What is your place of birth?'),
        ('mother_maiden', 'What is your mother\'s maiden name?'),
        ('first_school', 'What was the name of your first school?'),
        ('first_car', 'What was your first car?'),
        ('childhood_friend', 'What is the name of your childhood best friend?'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    custom_id = models.CharField(max_length=50, unique=True)
    mobile = models.CharField(max_length=20)
    is_admin = models.BooleanField(default=False)
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='user')
    
    # Security questions for password reset
    security_question = models.CharField(max_length=50, choices=SECURITY_QUESTION_CHOICES, blank=True, null=True)
    security_answer = models.CharField(max_length=255, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    
    date_added = models.DateTimeField(default=timezone.now)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'armsApp_userprofile'

    def __str__(self):
        return f"{self.user.username}'s Profile"

class Reservation(models.Model):
    flight = models.ForeignKey(Flights, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    type = models.CharField(max_length=50, choices=(('1','Business Class'), ('2','Economy')), default = '2')
    first_name = models.CharField(max_length=250)
    middle_name = models.CharField(max_length=250, null=True, blank=True)
    last_name = models.CharField(max_length=250)
    gender = models.CharField(max_length=50, choices=(('Male','Male'), ('Female','Female')), default = 'Male')
    email = models.CharField(max_length=250)
    contact = models.CharField(max_length=250)
    address = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=2, choices=(('0','Pending Admin Approval'),('1','Approved by Admin'),('2','Cancelled'),('3','Rejected by Admin')), default = 0)
    date_added = models.DateTimeField(default = timezone.now)
    date_created = models.DateTimeField(auto_now = True)
    seat_number = models.CharField(max_length=10, null=True, blank=True)

    class Meta:
        verbose_name_plural = "List of Reservations"

    def __str__(self):
        return str(f"{self.flight.code} - {self.first_name} {self.last_name}")
    
    def name(self):
        return str(f"{self.last_name}, {self.first_name} {self.middle_name}")
    
    def can_cancel(self):
        """
        Check if this reservation can be cancelled.
        Returns False if:
        1. Flight has already departed
        2. Reservation is already cancelled
        """
        from django.utils import timezone
        
        # Check if already cancelled
        if self.status == '2':
            return False
            
        # Check if flight has departed
        current_time = timezone.now()
        if self.flight.departure <= current_time:
            return False
            
        return True
    
    def get_cancellation_status(self):
        """
        Get a user-friendly message about why cancellation is not allowed
        """
        from django.utils import timezone
        
        if self.status == '2':
            return "Already cancelled"
        elif self.status == '3':
            return "Rejected by admin"
            
        current_time = timezone.now()
        if self.flight.departure <= current_time:
            return "Flight has departed"
            
        return "Can cancel"
    
    def get_status_display_text(self):
        """
        Get user-friendly status text with color coding
        """
        status_map = {
            '0': ('Pending Admin Approval', 'warning'),
            '1': ('Approved - Confirmed', 'success'), 
            '2': ('Cancelled', 'secondary'),
            '3': ('Rejected by Admin', 'danger')
        }
        return status_map.get(self.status, ('Unknown', 'secondary'))
    
    def can_be_approved(self):
        """
        Check if reservation can be approved by admin
        """
        from django.utils import timezone
        current_time = timezone.now()
        
        # Can only approve pending reservations for flights that haven't departed
        return self.status == '0' and self.flight.departure > current_time
    
    def approve_reservation(self):
        """
        Approve the reservation (admin action)
        """
        if self.can_be_approved():
            self.status = '1'
            self.save()
            
            # Create notification for user
            if self.user:
                from armsApp.models import UserNotification
                UserNotification.create_reservation_notification(self, 'reservation_approved')
            
            return True
        return False
    
    def reject_reservation(self):
        """
        Reject the reservation (admin action)
        """
        if self.status == '0':
            self.status = '3'
            self.save()
            
            # Create notification for user
            if self.user:
                from armsApp.models import UserNotification
                UserNotification.create_reservation_notification(self, 'reservation_rejected')
            
            return True
        return False


class FlightSchedule(models.Model):
    """Modified for migration trigger"""
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
    currency = models.CharField(max_length=3, default="INR", help_text="Currency code (INR for Indian Rupees)")
    
    # Schedule validity period
    start_date = models.DateField()
    end_date = models.DateField()
    
    # Status
    is_active = models.BooleanField(default=True)
    delete_flag = models.IntegerField(default=0)
    date_added = models.DateTimeField(default=timezone.now)
    date_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Flight Schedules"
    
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
                date_suffix = current_date.strftime('%m%d')
                flight_code = f"{self.code}-{date_suffix}"
                
                # Check if this flight already exists
                if not Flights.objects.filter(
                    code=flight_code,
                    airline=self.airline,
                    from_airport=self.from_airport,
                    to_airport=self.to_airport,
                    departure=departure_datetime
                ).exists():
                    flight = Flights(
                        code=flight_code,
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
                        currency=self.currency,
                        delete_flag=0,
                        date_added=timezone.now()
                    )
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


class UserNotification(models.Model):
    """
    Simple notification system for users
    """
    NOTIFICATION_TYPES = (
        ('reservation_approved', 'Reservation Approved'),
        ('reservation_rejected', 'Reservation Rejected'),
        ('general', 'General Notification'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES, default='general')
    title = models.CharField(max_length=255)
    message = models.TextField()
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "User Notifications"
    
    def __str__(self):
        return f"{self.user.username} - {self.title}"
    
    @classmethod
    def create_reservation_notification(cls, reservation, notification_type):
        """
        Create a notification for reservation approval/rejection
        """
        if notification_type == 'reservation_approved':
            title = f"Reservation Approved - Flight {reservation.flight.code}"
            message = f"""
            Great news! Your reservation for Flight {reservation.flight.code} has been approved by our admin team.
            
            Flight Details:
            - Route: {reservation.flight.from_airport.name} to {reservation.flight.to_airport.name}
            - Departure: {reservation.flight.departure.strftime('%B %d, %Y at %I:%M %p')}
            - Seat: {reservation.seat_number or 'Will be assigned'}
            - Class: {'Business Class' if reservation.type == '1' else 'Economy Class'}
            
            Your booking is now confirmed. Please arrive at the airport at least 2 hours before departure.
            """
        elif notification_type == 'reservation_rejected':
            title = f"Reservation Rejected - Flight {reservation.flight.code}"
            message = f"""
            We regret to inform you that your reservation for Flight {reservation.flight.code} has been rejected.
            
            Flight Details:
            - Route: {reservation.flight.from_airport.name} to {reservation.flight.to_airport.name}
            - Departure: {reservation.flight.departure.strftime('%B %d, %Y at %I:%M %p')}
            
            Possible reasons for rejection:
            - Flight capacity issues
            - Documentation problems
            - Payment verification issues
            
            Please contact our customer service for more details or try booking another flight.
            """
        else:
            return None
        
        notification = cls.objects.create(
            user=reservation.user,
            notification_type=notification_type,
            title=title,
            message=message,
            reservation=reservation
        )
        return notification
