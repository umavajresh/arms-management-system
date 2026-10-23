import datetime
import logging

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from armsApp.models import UserProfile

logger = logging.getLogger(__name__)

RESET_FLOW_LIFETIME_SECONDS = 600
MAX_RESET_ATTEMPTS = 5
RESET_SESSION_KEYS = (
    'reset_user_id',
    'identity_verified',
    'reset_expires_at',
    'reset_attempts',
)


def _clear_reset_flow(request):
    for key in RESET_SESSION_KEYS:
        request.session.pop(key, None)


def _begin_reset_flow(request, user_id):
    _clear_reset_flow(request)
    request.session['reset_user_id'] = user_id or 0
    request.session['reset_expires_at'] = (
        timezone.now() + datetime.timedelta(seconds=RESET_FLOW_LIFETIME_SECONDS)
    ).timestamp()
    request.session['reset_attempts'] = 0


def _reset_flow_is_valid(request):
    expires_at = request.session.get('reset_expires_at')
    if not expires_at or timezone.now().timestamp() >= expires_at:
        _clear_reset_flow(request)
        return False
    return True


def _record_reset_failure(request):
    attempts = request.session.get('reset_attempts', 0) + 1
    request.session['reset_attempts'] = attempts
    if attempts >= MAX_RESET_ATTEMPTS:
        _clear_reset_flow(request)
        return False
    return True


def forgot_password(request):
    context = {
        'page_title': 'Forgot Password',
        'topbar': False,
        'footer': False,
    }

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        user = User.objects.filter(username=username).first()
        if user is None:
            profile = UserProfile.objects.filter(custom_id=username).select_related('user').first()
            user = profile.user if profile else None

        profile = None
        if user is not None:
            try:
                profile = user.profile
            except UserProfile.DoesNotExist:
                pass

        if not profile or not all((
            profile.security_question,
            profile.security_answer,
            profile.date_of_birth,
        )):
            user = None

        _begin_reset_flow(request, user.pk if user else None)
        messages.info(
            request,
            "If the account can be verified, you can continue with password recovery.",
        )
        return redirect('verify-identity')

    return render(request, 'forgot_password.html', context)


def verify_identity(request):
    context = {
        'page_title': 'Verify Identity',
        'topbar': False,
        'footer': False,
    }

    user_id = request.session.get('reset_user_id')
    if user_id is None or not _reset_flow_is_valid(request):
        messages.error(request, "Session expired. Please restart the password reset process.")
        return redirect('forgot-password')
    if request.session.get('reset_attempts', 0) >= MAX_RESET_ATTEMPTS:
        _clear_reset_flow(request)
        messages.error(request, "Too many attempts. Please restart password recovery.")
        return redirect('forgot-password')

    profile = None
    if user_id:
        try:
            user = User.objects.get(id=user_id)
            profile = user.profile
        except (User.DoesNotExist, UserProfile.DoesNotExist):
            _clear_reset_flow(request)
            messages.error(request, "Session expired. Please restart the password reset process.")
            return redirect('forgot-password')
        except Exception:
            logger.exception("Unable to load password recovery profile")
            _clear_reset_flow(request)
            messages.error(request, "Password recovery is temporarily unavailable. Please restart the process.")
            return redirect('forgot-password')

    context['security_question_text'] = "Your recovery question is hidden for privacy."

    if request.method == 'POST':
        dob = request.POST.get('date_of_birth', '')
        answer = request.POST.get('security_answer', '').strip().casefold()
        try:
            dob_date = datetime.datetime.strptime(dob, '%Y-%m-%d').date()
        except ValueError:
            dob_date = None

        answer_matches = False
        if profile is not None and answer:
            try:
                answer_matches = check_password(answer, profile.security_answer)
            except ValueError:
                answer_matches = False
            if not answer_matches:
                answer_matches = constant_time_compare(
                    answer,
                    profile.security_answer.casefold(),
                )

        if (
            profile is None
            or dob_date != profile.date_of_birth
            or not answer_matches
        ):
            if not _record_reset_failure(request):
                messages.error(request, "Too many attempts. Please restart password recovery.")
                return redirect('forgot-password')
            messages.error(request, "The details did not match. Please try again.")
            return render(request, 'verify_identity.html', context)

        try:
            answer_is_hashed = check_password(answer, profile.security_answer)
        except ValueError:
            answer_is_hashed = False
        if not answer_is_hashed:
            profile.security_answer = make_password(answer)
            profile.save(update_fields=['security_answer'])

        request.session.cycle_key()
        request.session['identity_verified'] = True
        request.session['reset_attempts'] = 0
        return redirect('reset-password')

    return render(request, 'verify_identity.html', context)


def reset_password(request):
    context = {
        'page_title': 'Reset Password',
        'topbar': False,
        'footer': False,
    }

    if (
        not request.session.get('identity_verified')
        or not request.session.get('reset_user_id')
        or not _reset_flow_is_valid(request)
    ):
        _clear_reset_flow(request)
        messages.error(request, "Please verify your identity first.")
        return redirect('forgot-password')

    try:
        user = User.objects.get(id=request.session['reset_user_id'])
    except User.DoesNotExist:
        _clear_reset_flow(request)
        messages.error(request, "Session expired. Please restart the password reset process.")
        return redirect('forgot-password')
    except Exception:
        logger.exception("Unable to load user for password reset")
        _clear_reset_flow(request)
        messages.error(request, "Password reset is temporarily unavailable. Please try again.")
        return redirect('forgot-password')

    context['user'] = user
    if request.method == 'POST':
        new_password = request.POST.get('new_password') or ''
        confirm_password = request.POST.get('confirm_password') or ''
        response = {'status': 'failed', 'msg': ''}

        if not new_password or not confirm_password:
            response['msg'] = "Please fill in all fields."
        elif new_password != confirm_password:
            response['msg'] = "Passwords do not match."
        else:
            try:
                validate_password(new_password, user=user)
            except ValidationError as exc:
                response['msg'] = " ".join(exc.messages)
            else:
                user.set_password(new_password)
                user.save(update_fields=['password'])
                _clear_reset_flow(request)
                response.update(
                    status='success',
                    msg="Password has been reset successfully. You can now login with your new password.",
                )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(response)
        if response['status'] == 'success':
            messages.success(request, response['msg'])
            return redirect('login-page')
        messages.error(request, response['msg'])

    return render(request, 'reset_password.html', context)
