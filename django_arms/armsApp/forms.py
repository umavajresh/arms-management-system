from secrets import choice
from django import forms
from numpy import require
from armsApp import models
import qrcode
from django.contrib.auth.forms import UserCreationForm,PasswordChangeForm, UserChangeForm
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)

class SaveUser(UserCreationForm):
    username = forms.CharField(max_length=250,help_text="The Username field is required.")
    custom_id = forms.CharField(max_length=50, help_text="The User ID field is required and must be unique.")
    email = forms.EmailField(max_length=250,help_text="The Email field is required.")
    first_name = forms.CharField(max_length=250,help_text="The First Name field is required.")
    last_name = forms.CharField(max_length=250,help_text="The Last Name field is required.")
    mobile = forms.CharField(max_length=20, help_text="The Mobile Number field is required.")
    
    # Security question fields for password recovery
    security_question = forms.ChoiceField(
        choices=models.UserProfile.SECURITY_QUESTION_CHOICES,
        help_text="Select a security question for password recovery."
    )
    security_answer = forms.CharField(
        max_length=255,
        help_text="Your answer to the security question."
    )
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text="Your date of birth for account verification."
    )
    
    password1 = forms.CharField(max_length=250)
    password2 = forms.CharField(max_length=250)
    
    class Meta:
        model = User
        fields = ('email', 'username', 'first_name', 'last_name', 'password1', 'password2')
        # Note: custom_id, mobile, and security fields are not included here because they're saved in the UserProfile model
    
    def clean_custom_id(self):
        custom_id = self.cleaned_data.get('custom_id')
        if not custom_id:
            raise forms.ValidationError("User ID is required")
            
        try:
            from armsApp.models import UserProfile
            profile = UserProfile.objects.filter(custom_id=custom_id).first()
            if profile:
                raise forms.ValidationError("User ID is already taken")
        except Exception as e:
            logger.exception("Error checking custom_id")
            # Don't suppress unexpected exceptions
            if "DoesNotExist" not in str(e) and "no such table" not in str(e):
                raise e
        return custom_id
        
    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile')
        if not mobile:
            raise forms.ValidationError("Mobile number is required")
        return mobile
        
    def clean_security_answer(self):
        answer = self.cleaned_data.get('security_answer')
        if not answer:
            raise forms.ValidationError("Security answer is required")
        # Store the answer in lowercase to make later verification case-insensitive
        return answer.lower()

class UpdateProfile(UserChangeForm):
    username = forms.CharField(max_length=250,help_text="The Username field is required.")
    email = forms.EmailField(max_length=250,help_text="The Email field is required.")
    first_name = forms.CharField(max_length=250,help_text="The First Name field is required.")
    last_name = forms.CharField(max_length=250,help_text="The Last Name field is required.")
    current_password = forms.CharField(max_length=250)

    class Meta:
        model = User
        fields = ('email', 'username','first_name', 'last_name')

    def clean_current_password(self):
        if not self.instance.check_password(self.cleaned_data['current_password']):
            raise forms.ValidationError(f"Password is Incorrect")

    def clean_email(self):
        email = self.cleaned_data['email']
        try:
            user = User.objects.exclude(id=self.cleaned_data['id']).get(email = email)
        except Exception as e:
            return email
        raise forms.ValidationError(f"The {user.email} mail is already exists/taken")

    def clean_username(self):
        username = self.cleaned_data['username']
        try:
            user = User.objects.exclude(id=self.cleaned_data['id']).get(username = username)
        except Exception as e:
            return username
        raise forms.ValidationError(f"The {user.username} mail is already exists/taken")

class UpdatePasswords(PasswordChangeForm):
    old_password = forms.CharField(widget=forms.PasswordInput(attrs={'class':'form-control form-control-sm rounded-0'}), label="Old Password")
    new_password1 = forms.CharField(widget=forms.PasswordInput(attrs={'class':'form-control form-control-sm rounded-0'}), label="New Password")
    new_password2 = forms.CharField(widget=forms.PasswordInput(attrs={'class':'form-control form-control-sm rounded-0'}), label="Confirm New Password")
    class Meta:
        model = User
        fields = ('old_password','new_password1', 'new_password2')

class SaveAirlines(forms.ModelForm):
    code = forms.CharField(max_length=5)
    name = forms.CharField(max_length=250)
    country = forms.CharField(max_length=100, required=False)
    status = forms.CharField(max_length=2)
    image_path = forms.ImageField(required=False)

    class Meta:
        model = models.Airlines
        fields = ('code', 'name', 'country', 'status', 'image_path', )

    def clean_code(self):
        id = self.data['id'] if (self.data['id']).isnumeric() else 0
        code = self.cleaned_data['code']
        try:
            if id > 0:
                airline = models.Airlines.objects.exclude(id = id).get(code = code, delete_flag = 0)
            else:
                airline = models.Airlines.objects.get(code = code, delete_flag = 0)
        except:
            return code
        raise forms.ValidationError("Airline code already exists")
        
    def clean_name(self):
        id = self.data['id'] if (self.data['id']).isnumeric() else 0
        name = self.cleaned_data['name']
        try:
            if id > 0:
                airline = models.Airlines.objects.exclude(id = id).get(name = name, delete_flag = 0)
            else:
                airline = models.Airlines.objects.get(name = name, delete_flag = 0)
        except:
            return name
        raise forms.ValidationError("Airline name already exists")


class SaveAirports(forms.ModelForm):
    code = forms.CharField(max_length=5)
    name = forms.CharField(max_length=250)
    city = forms.CharField(max_length=100, required=False)
    country = forms.CharField(max_length=100, required=False)
    status = forms.CharField(max_length=2)

    class Meta:
        model = models.Airport
        fields = ('code', 'name', 'city', 'country', 'status', )

    def clean_code(self):
        id = self.data['id'] if (self.data['id']).isnumeric() else 0
        code = self.cleaned_data['code']
        try:
            if id > 0:
                airport = models.Airport.objects.exclude(id = id).get(code = code, delete_flag = 0)
            else:
                airport = models.Airport.objects.get(code = code, delete_flag = 0)
        except:
            return code
        raise forms.ValidationError("Airport code already exists")
        
    def clean_name(self):
        id = self.data['id'] if (self.data['id']).isnumeric() else 0
        name = self.cleaned_data['name']
        try:
            if id > 0:
                airport = models.Airport.objects.exclude(id = id).get(name = name, delete_flag = 0)
            else:
                airport = models.Airport.objects.get(name = name, delete_flag = 0)
        except:
            return name
        raise forms.ValidationError("Airport name already exists")
        
class SaveAircraft(forms.ModelForm):
    code = forms.CharField(max_length=5)
    model = forms.CharField(max_length=250)
    manufacturer = forms.CharField(max_length=100)
    business_capacity = forms.IntegerField()
    economy_capacity = forms.IntegerField()
    status = forms.CharField(max_length=2)

    class Meta:
        model = models.Aircraft
        fields = ('code', 'model', 'manufacturer', 'business_capacity', 'economy_capacity', 'status', )

    def clean_code(self):
        id = self.data['id'] if (self.data['id']).isnumeric() else 0
        code = self.cleaned_data['code']
        try:
            if id > 0:
                aircraft = models.Aircraft.objects.exclude(id = id).get(code = code, delete_flag = 0)
            else:
                aircraft = models.Aircraft.objects.get(code = code, delete_flag = 0)
        except:
            return code
        raise forms.ValidationError("Aircraft code already exists")

class SaveFlights(forms.ModelForm):
    code = forms.CharField(max_length=250)
    airline = forms.CharField(max_length=250)
    from_airport = forms.CharField(max_length=250)
    to_airport = forms.CharField(max_length=250)
    aircraft = forms.CharField(max_length=250)
    departure = forms.DateTimeField()
    estimated_arrival = forms.DateTimeField()
    business_class_price = forms.CharField(max_length=250)
    economy_price = forms.CharField(max_length=250)
    currency = forms.CharField(max_length=3, initial="INR", required=False)

    class Meta:
        model = models.Flights
        fields = ('code', 'airline', 'from_airport', 'to_airport', 'aircraft', 'departure', 'estimated_arrival', 'business_class_price', 'economy_price', 'currency', )

    def clean_code(self):
        id = self.data['id'] if (self.data['id']).isnumeric() else 0
        code = self.cleaned_data['code']
        try:
            if id > 0:
                flight = models.Flights.objects.exclude(id = id).get(code = code, delete_flag = 0)
            else:
                flight = models.Flights.objects.get(code = code, delete_flag = 0)
        except:
            return code
        raise forms.ValidationError("Flight Code is already exists")

    def clean_airline(self):
        aid = self.cleaned_data['airline']
        try:
            airline = models.Airlines.objects.get(id = aid)
            return airline
        except:
            raise forms.ValidationError(f"The selected airline is invalied")
    
    def clean_from_airport(self):
        aid = self.cleaned_data['from_airport']
        try:
            airport = models.Airport.objects.get(id = aid)
            return airport
        except:
            raise forms.ValidationError(f"The selected From Airport is invalied")

    def clean_to_airport(self):
        aid = self.cleaned_data['to_airport']
        try:
            airport = models.Airport.objects.get(id = aid)
            return airport
        except:
            raise forms.ValidationError(f"The selected To Airport is invalid")
            
    def clean_aircraft(self):
        aid = self.cleaned_data['aircraft']
        try:
            aircraft = models.Aircraft.objects.get(id = aid)
            # Set the business_class_slots and economy_slots based on the aircraft capacity
            self.cleaned_data['business_class_slots'] = aircraft.business_capacity
            self.cleaned_data['economy_slots'] = aircraft.economy_capacity
            return aircraft
        except:
            raise forms.ValidationError(f"The selected Aircraft is invalid")

class SaveReservation(forms.ModelForm):
    flight = forms.CharField(max_length=250)
    type = forms.CharField(max_length=250)
    first_name = forms.CharField(max_length=250)
    middle_name = forms.CharField(max_length=250, required=False)
    last_name = forms.CharField(max_length=250)
    gender = forms.CharField(max_length=250)
    contact = forms.CharField(max_length=250)
    email = forms.CharField(max_length=250)
    address = forms.CharField(widget=forms.Textarea(), required=False)
    seat_number = forms.CharField(max_length=10, required=False)


    class Meta:
        model = models.Reservation
        fields = ('flight', 'type', 'first_name', 'middle_name', 'last_name', 'gender', 'contact', 'email', 'address', 'seat_number')

    def clean_flight(self):
        fid = self.cleaned_data['flight']
        try:
            flight = models.Flights.objects.get(id = fid)
            return flight
        except:
            raise forms.ValidationError(f"Invalid Flight")


class ReservationVerificationForm(forms.Form):
    """
    Form for verifying user password and CAPTCHA before confirming reservation
    """
    from captcha.fields import CaptchaField
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter your password'}),
        label='Password Verification'
    )
    captcha = CaptchaField(label='Security Check')
    
    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        
    def clean_password(self):
        password = self.cleaned_data.get('password')
        if self.user and not self.user.check_password(password):
            raise forms.ValidationError("Incorrect password.")
        return password
    