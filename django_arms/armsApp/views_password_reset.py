import datetime
from django.shortcuts import redirect, render
import json
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.utils import timezone
from armsApp import models, forms
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
import logging

logger = logging.getLogger(__name__)

# Add the new password reset views
def forgot_password(request):
    context = {
        'page_title': 'Forgot Password',
        'topbar': False,
        'footer': False
    }
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        
        if not username:
            messages.error(request, "Please provide your username or ID")
            return render(request, 'forgot_password.html', context)
        
        # Try to find user by username or custom_id
        user = None
        try:
            # First check if it's a username
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            # Then check if it's a custom_id
            try:
                from armsApp.models import UserProfile
                profile = UserProfile.objects.get(custom_id=username)
                user = profile.user
            except UserProfile.DoesNotExist:
                logger.debug("UserProfile not found for custom_id: %s", username)
        
        if not user:
            messages.error(request, "No account found with that username or ID")
            return render(request, 'forgot_password.html', context)
        
        # Check if user has security question set
        try:
            profile = user.profile
            if not profile.security_question or not profile.security_answer:
                messages.error(request, "Security questions not set for this account. Please contact administrator.")
                return render(request, 'forgot_password.html', context)
                
            # Store user_id in session for next step
            request.session['reset_user_id'] = user.id
            
            # Redirect to security question verification
            return redirect('verify-identity')
            
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
    
    return render(request, 'forgot_password.html', context)

def verify_identity(request):
    context = {
        'page_title': 'Verify Identity',
        'topbar': False,
        'footer': False
    }
    
    # Check if we have a user_id in session
    user_id = request.session.get('reset_user_id')
    if not user_id:
        messages.error(request, "Session expired. Please restart the password reset process.")
        return redirect('forgot-password')
    
    try:
        # Get the user and profile
        user = User.objects.get(id=user_id)
        profile = user.profile
        
        # Add user and security question to context
        context['user'] = user
        
        # Get the full text of the security question
        from armsApp.models import UserProfile
        security_questions = dict(UserProfile.SECURITY_QUESTION_CHOICES)
        context['security_question_text'] = security_questions.get(profile.security_question, profile.security_question)
        
        # Handle form submission
        if request.method == 'POST':
            dob = request.POST.get('date_of_birth')
            answer = request.POST.get('security_answer', '').lower()  # Convert to lowercase
            
            # Check date of birth
            if dob:
                try:
                    dob_date = datetime.datetime.strptime(dob, '%Y-%m-%d').date()
                    if dob_date != profile.date_of_birth:
                        messages.error(request, "Date of birth does not match our records.")
                        return render(request, 'verify_identity.html', context)
                except:
                    messages.error(request, "Invalid date format.")
                    return render(request, 'verify_identity.html', context)
            else:
                messages.error(request, "Please enter your date of birth.")
                return render(request, 'verify_identity.html', context)
            
            # Check security answer
            if not answer:
                messages.error(request, "Please provide an answer to the security question.")
                return render(request, 'verify_identity.html', context)
            
            if answer.strip().lower() != profile.security_answer.strip().lower():
                messages.error(request, "Security answer does not match our records.")
                return render(request, 'verify_identity.html', context)
            
            # If everything matches, mark verification as successful
            request.session['identity_verified'] = True
            
            # Redirect to reset password page
            return redirect('reset-password')
            
    except User.DoesNotExist:
        messages.error(request, "User not found. Please restart the password reset process.")
        return redirect('forgot-password')
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('forgot-password')
    
    return render(request, 'verify_identity.html', context)

def reset_password(request):
    context = {
        'page_title': 'Reset Password',
        'topbar': False,
        'footer': False
    }
    
    # Check if user is verified
    if not request.session.get('identity_verified'):
        messages.error(request, "Please verify your identity first.")
        return redirect('forgot-password')
    
    # Get user from session
    user_id = request.session.get('reset_user_id')
    if not user_id:
        messages.error(request, "Session expired. Please restart the password reset process.")
        return redirect('forgot-password')
    
    try:
        user = User.objects.get(id=user_id)
        context['user'] = user
        
        if request.method == 'POST':
            resp = {'status': 'failed', 'msg': ''}
            
            new_password = request.POST.get('new_password')
            confirm_password = request.POST.get('confirm_password')
            
            if not new_password or not confirm_password:
                resp['msg'] = "Please fill in all fields."
            elif new_password != confirm_password:
                resp['msg'] = "Passwords do not match."
            elif len(new_password) < 6:
                resp['msg'] = "Password must be at least 6 characters long."
            else:
                # Set the new password
                user.set_password(new_password)
                user.save()
                
                # Clear session data
                request.session.pop('reset_user_id', None)
                request.session.pop('identity_verified', None)
                
                resp['status'] = 'success'
                resp['msg'] = "Password has been reset successfully. You can now login with your new password."
                
                # If it's not an AJAX request, redirect to login
                if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    messages.success(request, resp['msg'])
                    return redirect('login-page')
            
            # Return JSON for AJAX requests
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return HttpResponse(json.dumps(resp), content_type='application/json')
            else:
                messages.error(request, resp['msg'])
                
    except User.DoesNotExist:
        messages.error(request, "User not found. Please restart the password reset process.")
        return redirect('forgot-password')
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return HttpResponse(json.dumps({'status': 'failed', 'msg': str(e)}), content_type='application/json')
    
    return render(request, 'reset_password.html', context)