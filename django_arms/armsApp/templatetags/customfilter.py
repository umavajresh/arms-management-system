from django import template
from cryptography.fernet import Fernet
from django.conf import settings

register = template.Library()

@register.filter
def replaceBlank(value, stringVal=""):
    value = str(value).replace(stringVal, '')
    return value

@register.filter
def encryptdata(value):
    fernet = Fernet(settings.ID_ENCRYPTION_KEY)
    value = fernet.encrypt(str(value).encode())
    return value

@register.filter(name="inr")
def inr(value):
    """
    Format a number as Indian Rupees with thousands separator
    Example: 50000 becomes ₹50,000.00
    """
    try:
        value = float(value)
        formatted = "₹{:,.2f}".format(value)
        return formatted
    except (ValueError, TypeError):
        return value
