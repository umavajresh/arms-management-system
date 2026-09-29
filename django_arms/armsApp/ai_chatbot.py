import os
import re
from datetime import datetime

from django.db.models import Q
from django.utils import timezone
from .models import Flights

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None


def _parse_indian_currency(value):
    if value is None:
        return None
    cleaned = str(value).strip().lower().replace(',', '')
    cleaned = cleaned.replace('₹', '').replace('rs', '').replace('inr', '')
    cleaned = cleaned.replace('rupees', '').replace('rupee', '')
    cleaned = cleaned.replace('under', '').replace('about', '').replace('around', '')
    match = re.search(r'(\d+(?:\.\d+)?)', cleaned)
    if not match:
        return None
    return float(match.group(1))


def _parse_city_name(message):
    text = message.lower()
    city_hint = None
    if 'from ' in text:
        candidate = text.split('from', 1)[1].split()[0]
        if candidate:
            city_hint = candidate.strip(' ,.')
    elif 'traveling from ' in text:
        candidate = text.split('traveling from', 1)[1].split()[0]
        if candidate:
            city_hint = candidate.strip(' ,.')
    elif 'departing from ' in text:
        candidate = text.split('departing from', 1)[1].split()[0]
        if candidate:
            city_hint = candidate.strip(' ,.')
    return city_hint or ''


def extract_travel_preferences(message):
    text = message or ''
    lower_text = text.lower()
    budget = None
    for pattern in [r'budget(?: is| of)?\s*(?:₹|rs|inr)?\s*\d[\d,]*(?:\.\d+)?',
                    r'(?:₹|rs|inr)\s*\d[\d,]*(?:\.\d+)?',
                    r'under\s*(?:₹|rs|inr)?\s*\d[\d,]*(?:\.\d+)?']:
        match = re.search(pattern, lower_text)
        if match:
            budget = _parse_indian_currency(match.group(0))
            if budget:
                break

    days_match = re.search(r'(\d+)\s*(?:day|days)', lower_text)
    days = int(days_match.group(1)) if days_match else None

    origin = _parse_city_name(text)
    if not origin and 'chennai' in lower_text:
        origin = 'Chennai'

    destination = None
    for keyword in ['goa', 'delhi', 'hyderabad', 'mumbai', 'bangalore', 'kochi', 'jaipur', 'ooty', 'shimla']:
        if keyword in lower_text:
            destination = keyword.title()
            break

    month = None
    if 'next month' in lower_text or 'upcoming month' in lower_text:
        month = 'next month'
    elif 'this month' in lower_text:
        month = 'this month'
    elif 'january' in lower_text or 'february' in lower_text or 'march' in lower_text or 'april' in lower_text or 'may' in lower_text or 'june' in lower_text or 'july' in lower_text or 'august' in lower_text or 'september' in lower_text or 'october' in lower_text or 'november' in lower_text or 'december' in lower_text:
        month = 'specific month'

    preferences = []
    if 'historical' in lower_text:
        preferences.append('historical places')
    if 'beach' in lower_text or 'coast' in lower_text:
        preferences.append('beach destinations')
    if 'nature' in lower_text or 'hill' in lower_text or 'forest' in lower_text:
        preferences.append('nature and hill stations')
    if 'adventure' in lower_text or 'trek' in lower_text:
        preferences.append('adventure activities')
    if 'family' in lower_text:
        preferences.append('family-friendly options')

    return {
        'budget': budget,
        'days': days,
        'origin': origin,
        'destination': destination,
        'month': month,
        'preferences': preferences,
        'message': text,
    }


def _build_local_recommendations(prefs):
    budget = prefs.get('budget') or 12000
    days = prefs.get('days') or 3
    origin = (prefs.get('origin') or 'Chennai').strip()
    destination = prefs.get('destination')
    preferences = prefs.get('preferences') or []

    defaults = [
        {'name': 'Goa', 'flight_cost': 3200, 'hotel_cost': 4500, 'trip_length': '3 days', 'highlights': 'Beach, nightlife, relaxed weekend escape'},
        {'name': 'Hyderabad', 'flight_cost': 2800, 'hotel_cost': 3500, 'trip_length': '3 days', 'highlights': 'Historic sites, food, city sightseeing'},
        {'name': 'Delhi', 'flight_cost': 3600, 'hotel_cost': 4000, 'trip_length': '3 days', 'highlights': 'Monuments, shopping, heritage tours'},
        {'name': 'Bangalore', 'flight_cost': 3000, 'hotel_cost': 4200, 'trip_length': '3 days', 'highlights': 'Food, cafes, cultural spots'},
    ]

    if destination:
        defaults = [
            {'name': destination, 'flight_cost': int(max(1800, budget * 0.28)), 'hotel_cost': int(max(2200, budget * 0.35)), 'trip_length': f'{days} days', 'highlights': 'Suggested based on your travel preferences'}
        ] + [item for item in defaults if item['name'] != destination]

    ranked = []
    for item in defaults:
        total_cost = item['flight_cost'] + item['hotel_cost'] + max(500, int((budget * 0.08)))
        if total_cost <= budget * 1.4:
            ranked.append({**item, 'estimated_total': total_cost})
    if not ranked:
        ranked = [{
            'name': destination or 'Hyderabad',
            'flight_cost': min(int(budget * 0.35), 5000),
            'hotel_cost': min(int(budget * 0.42), 6000),
            'trip_length': f'{days} days',
            'highlights': 'Good fit based on your budget and travel preferences',
            'estimated_total': int(budget * 0.9),
        }]

    if preferences:
        for item in ranked:
            item['highlights'] = f"{item['highlights']} • {', '.join(preferences[:2])}"

    return ranked[:3]

def search_real_flights(prefs, limit=5):
    """
    Search actual flights from the ARMS database.
    """

    queryset = Flights.objects.filter(
        delete_flag=0,
        departure__gt=timezone.now()
    ).select_related(
        'airline',
        'from_airport',
        'to_airport'
    )

    origin = (prefs.get('origin') or '').strip()
    destination = (prefs.get('destination') or '').strip()
    budget = prefs.get('budget')

    if origin:
        queryset = queryset.filter(
            Q(from_airport__name__icontains=origin) |
            Q(from_airport__code__icontains=origin)
        )

    if destination:
        queryset = queryset.filter(
            Q(to_airport__name__icontains=destination) |
            Q(to_airport__code__icontains=destination)
        )

    if budget:
        queryset = queryset.filter(
            economy_price__lte=budget
        )

    flights = []

    for flight in queryset.order_by('economy_price')[:limit]:

        economy_available = flight.e_slot()
        business_available = flight.b_slot()

        if economy_available <= 0 and business_available <= 0:
            continue

        flights.append({
            'id': flight.id,
            'code': flight.code,
            'airline': str(flight.airline),
            'from': str(flight.from_airport),
            'to': str(flight.to_airport),
            'departure': flight.departure.strftime('%d %b %Y, %I:%M %p'),
            'arrival': flight.estimated_arrival.strftime('%d %b %Y, %I:%M %p'),
            'economy_price': flight.economy_price,
            'business_price': flight.business_class_price,
            'economy_available': economy_available,
            'business_available': business_available,
        })

    return flights
def get_travel_response(message):
    prefs = extract_travel_preferences(message)
    budget = prefs.get('budget')
    days = prefs.get('days') or 3

    api_key = os.getenv("OPENAI_API_KEY")
    if api_key and OpenAI is not None:
        try:
            client = OpenAI(api_key=api_key)
            response = client.responses.create(
                model="gpt-5-mini",
                instructions="""
You are an AI travel assistant for the ARMS flight booking website.

Help users with:
- Choosing destinations
- Travel month
- Budget
- Number of people
- Travel preferences
- Flight-related questions

Always keep suggestions practical, short, and friendly.
Never claim a ticket has been booked; actual booking happens in Django.
""",
                input=message,
            )
            return response.output_text
        except Exception:
            pass

    recommendations = _build_local_recommendations(prefs)
    origin_label = prefs.get('origin') or 'your city'
    budget_text = f"₹{int(budget):,}" if budget else "your stated budget"
    lines = [
        f"Budget: {budget_text} for {days} days. Based on your travel preferences, I recommend these options from {origin_label}:",
        "",
    ]
    for item in recommendations:
        lines.append(f"- {item['name']}: Estimated total {item['estimated_total']:,} INR | Flight ~ ₹{item['flight_cost']:,} | Hotel ~ ₹{item['hotel_cost']:,} | Best for: {item['highlights']}")
    lines.extend([
        "",
        "If you want, I can also narrow this down to flights under a specific price or search destinations around your preferred month.",
    ])
    return "\n".join(lines)
