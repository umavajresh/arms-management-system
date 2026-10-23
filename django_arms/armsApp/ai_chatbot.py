import os
import re
from datetime import datetime, timedelta

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
    match = re.search(
        r'\b(?:from|departing from|traveling from|travelling from)\s+'
        r'([a-z][a-z .\'-]*?)(?=\s+(?:for|to|with|during|in|on)\b|[,.;!?]|$)',
        message or '',
        re.IGNORECASE,
    )
    return match.group(1).strip().title() if match else ''


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

    destination_aliases = {
        'goa': 'Goa', 'delhi': 'Delhi', 'hyderabad': 'Hyderabad',
        'mumbai': 'Mumbai', 'bangalore': 'Bangalore', 'bengaluru': 'Bangalore',
        'kochi': 'Kochi', 'jaipur': 'Jaipur', 'ooty': 'Ooty', 'shimla': 'Shimla',
        'dubai': 'Dubai', 'bangkok': 'Bangkok', 'singapore': 'Singapore',
        'bali': 'Bali', 'denpasar': 'Bali', 'paris': 'Paris', 'london': 'London',
        'tokyo': 'Tokyo', 'kuala lumpur': 'Kuala Lumpur', 'colombo': 'Colombo',
        'kathmandu': 'Kathmandu', 'male': 'Male',
    }
    destination = next(
        (name for keyword, name in destination_aliases.items()
         if keyword in lower_text and name.lower() != origin.lower()),
        None,
    )

    trip_type = 'domestic'
    if any(keyword in lower_text for keyword in ['international', 'abroad', 'overseas', 'foreign trip', 'foreign travel']):
        trip_type = 'international'
    elif destination in {
        'Dubai', 'Bangkok', 'Singapore', 'Bali', 'Paris', 'London', 'Tokyo',
        'Kuala Lumpur', 'Colombo', 'Kathmandu', 'Male',
    }:
        trip_type = 'international'

    month = None
    if 'next month' in lower_text or 'upcoming month' in lower_text:
        month = 'next month'
    elif 'this month' in lower_text:
        month = 'this month'
    else:
        month = next((name.title() for name in (
            'january', 'february', 'march', 'april', 'may', 'june', 'july',
            'august', 'september', 'october', 'november', 'december'
        ) if re.search(rf'\b{name}\b', lower_text)), None)

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
    if any(word in lower_text for word in ('food', 'cuisine', 'street food')):
        preferences.append('food experiences')
    if any(word in lower_text for word in ('culture', 'museum', 'heritage', 'temple')):
        preferences.append('culture and heritage')
    if any(word in lower_text for word in ('nightlife', 'clubs', 'bars')):
        preferences.append('nightlife')

    return {
        'budget': budget,
        'days': days,
        'origin': origin,
        'destination': destination,
        'trip_type': trip_type,
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
    trip_type = prefs.get('trip_type', 'domestic')

    international_options = [
        {'name': 'Dubai', 'flight_cost': 42000, 'hotel_night': 12000, 'daily_cost': 9000, 'highlights': 'Desert safari, old Dubai, and the downtown skyline'},
        {'name': 'Bangkok', 'flight_cost': 28000, 'hotel_night': 7000, 'daily_cost': 7000, 'highlights': 'Temples, markets, and Thai street food'},
        {'name': 'Singapore', 'flight_cost': 36000, 'hotel_night': 12000, 'daily_cost': 10000, 'highlights': 'Gardens by the Bay, Chinatown, and Marina Bay'},
        {'name': 'Bali', 'flight_cost': 25000, 'hotel_night': 8000, 'daily_cost': 8000, 'highlights': 'Ubud, rice terraces, and a south-coast beach'},
        {'name': 'Paris', 'flight_cost': 60000, 'hotel_night': 18000, 'daily_cost': 14000, 'highlights': 'Central Paris, a museum, and a Seine-side walk'},
        {'name': 'Kuala Lumpur', 'flight_cost': 24000, 'hotel_night': 7000, 'daily_cost': 7000, 'highlights': 'Food markets, heritage quarter, and city views'},
        {'name': 'Colombo', 'flight_cost': 18000, 'hotel_night': 7000, 'daily_cost': 7000, 'highlights': 'Coastal city sights, markets, and local cuisine'},
        {'name': 'Kathmandu', 'flight_cost': 22000, 'hotel_night': 6000, 'daily_cost': 7000, 'highlights': 'Historic squares and Himalayan culture'},
    ]
    domestic_options = [
        {'name': 'Goa', 'flight_cost': 6500, 'hotel_night': 7000, 'daily_cost': 5000, 'highlights': 'Beach time, old Goa, and relaxed local food'},
        {'name': 'Hyderabad', 'flight_cost': 5500, 'hotel_night': 6000, 'daily_cost': 4500, 'highlights': 'Charminar, old-city food, and a fort visit'},
        {'name': 'Delhi', 'flight_cost': 7000, 'hotel_night': 7500, 'daily_cost': 6000, 'highlights': 'One heritage district, a major monument, and local food'},
        {'name': 'Bangalore', 'flight_cost': 6000, 'hotel_night': 7000, 'daily_cost': 5000, 'highlights': 'Garden, food neighborhoods, and a day trip option'},
        {'name': 'Jaipur', 'flight_cost': 7500, 'hotel_night': 6500, 'daily_cost': 5000, 'highlights': 'Amber Fort, the old city, and Rajasthani cuisine'},
        {'name': 'Kochi', 'flight_cost': 7000, 'hotel_night': 6500, 'daily_cost': 5000, 'highlights': 'Fort Kochi, waterfront, and Kerala cuisine'},
    ]
    options = international_options if trip_type == 'international' else domestic_options
    if destination:
        requested = [option for option in options if option['name'].lower() == destination.lower()]
        options = requested or options

    nights = max(0, days - 1)
    ranked = []
    for option in options:
        estimate = option['flight_cost'] + option['hotel_night'] * nights + option['daily_cost'] * days
        style_score = _preference_match_score(option['highlights'], preferences)
        ranked.append({
            **option,
            'trip_length': f'{days} days',
            'hotel_cost': option['hotel_night'] * nights,
            'estimated_total': estimate,
            'within_budget': estimate <= budget,
            'style_score': style_score,
        })
    ranked.sort(key=lambda item: (
        not item['within_budget'], -item['style_score'], item['estimated_total']
    ))

    if preferences:
        for item in ranked:
            item['highlights'] = f"{item['highlights']}; suited to {', '.join(preferences[:2])}"
    return ranked[:3]


def _preference_match_score(highlights, preferences):
    terms = {
        'historical places': ('historic', 'heritage', 'old city', 'square'),
        'beach destinations': ('beach', 'coastal', 'coast'),
        'nature and hill stations': ('rice terraces', 'waterfall', 'himalayan', 'garden'),
        'adventure activities': ('safari', 'trek', 'adventure'),
        'family-friendly options': ('family', 'garden', 'museum'),
        'food experiences': ('food', 'cuisine', 'market', 'hawker'),
        'culture and heritage': ('temple', 'heritage', 'historic', 'museum', 'cultural'),
        'nightlife': ('nightlife', 'bars', 'clubs'),
    }
    text = highlights.lower()
    return sum(
        any(term in text for term in terms.get(preference, ()))
        for preference in preferences
    )

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

    if not origin:
        return []

    if origin:
        queryset = queryset.filter(
            Q(from_airport__name__icontains=origin) |
            Q(from_airport__code__icontains=origin) |
            Q(from_airport__city__icontains=origin)
        )

    if destination:
        aliases = {'bali': ('Bali', 'Denpasar')}.get(destination.lower(), (destination,))
        destination_query = Q()
        for alias in aliases:
            destination_query |= (
                Q(to_airport__name__icontains=alias) |
                Q(to_airport__code__icontains=alias) |
                Q(to_airport__city__icontains=alias)
            )
        queryset = queryset.filter(destination_query)
    elif prefs.get('trip_type') == 'international':
        queryset = queryset.exclude(to_airport__country__iexact='India').exclude(to_airport__country='')

    month = prefs.get('month')
    if month in ('this month', 'next month'):
        month_start = timezone.localdate().replace(day=1)
        if month == 'next month':
            month_start = (month_start + timedelta(days=32)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        queryset = queryset.filter(departure__date__gte=month_start, departure__date__lt=month_end)
    elif month:
        month_number = datetime.strptime(month, '%B').month
        current_date = timezone.localdate()
        year = current_date.year + (month_number < current_date.month)
        queryset = queryset.filter(departure__year=year, departure__month=month_number)

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
            'currency': flight.currency,
            'economy_available': economy_available,
            'business_available': business_available,
        })

    return flights
def _check_faq_or_flight_status(message):
    lower = (message or '').strip().lower()

    # Flight status check
    flight_match = re.search(r'\b([a-zA-Z]{2,4}\s*[-]?\s*\d{2,4})\b', message or '', re.IGNORECASE)
    if flight_match and any(keyword in lower for keyword in ['status', 'track', 'flight', 'delayed', 'departure', 'where is', 'on time', 'info']):
        raw_code = flight_match.group(1).replace(' ', '').replace('-', '').upper()
        flight = Flights.objects.filter(
            Q(code__iexact=raw_code) | Q(code__icontains=raw_code),
            delete_flag=0,
        ).select_related('airline', 'from_airport', 'to_airport', 'aircraft').first()
        if flight:
            now = timezone.now()
            if flight.departure > now:
                status_str = "Scheduled (On-time)"
            elif flight.estimated_arrival > now:
                status_str = "In-Flight (En Route)"
            else:
                status_str = "Landed (Completed)"

            e_available = flight.e_slot()
            b_available = flight.b_slot()

            return "\n".join([
                f"Flight Status for {flight.code} ({flight.airline.name}):",
                f"- Route: {flight.from_airport.name} ({flight.from_airport.code}) to {flight.to_airport.name} ({flight.to_airport.code})",
                f"- Scheduled Departure: {flight.departure.strftime('%d %b %Y, %I:%M %p')}",
                f"- Scheduled Arrival: {flight.estimated_arrival.strftime('%d %b %Y, %I:%M %p')}",
                f"- Aircraft: {flight.aircraft.model} ({flight.aircraft.code})",
                f"- Current Status: {status_str}",
                f"- Available Seats: {e_available} Economy, {b_available} Business",
                f"- Live Tracker: [Track Live Flight](/flight_tracker?flight={flight.code})",
                f"- Book Seats: [Select Seats](/seat_selection/{flight.id})",
            ])

    # Baggage FAQ
    if any(k in lower for k in ['baggage', 'luggage', 'cabin bag', 'check-in bag', 'weight limit']):
        return "\n".join([
            "ARMS Airline Baggage Policy:",
            "- Cabin Baggage: 1 piece up to 7 kg (dimensions up to 55 x 35 x 25 cm) plus 1 small personal item (handbag or laptop bag).",
            "- Domestic Check-in Baggage: Economy allows 1 piece up to 15 kg; Business Class allows up to 25 kg.",
            "- International Check-in Baggage: Economy allows up to 30 kg; Business Class allows up to 40 kg (max 2 pieces).",
            "- Excess Baggage: Can be pre-booked at discounted rates during reservation or managed at the airport counter.",
            "For specific flight details, you can view your itinerary in [My Bookings](/user_reservations).",
        ])

    # Cancellation FAQ
    if 'cancel' in lower and any(k in lower for k in ['policy', 'how', 'booking', 'reservation', 'ticket', 'refund']):
        return "\n".join([
            "ARMS Reservation Cancellation & Refund Guidelines:",
            "- Self-Service Cancellation: Passengers can cancel any pending or confirmed booking from [My Bookings](/user_reservations) as long as the scheduled flight has not yet departed.",
            "- Past Departures: Flights that have already departed cannot be cancelled.",
            "- Administrative Review: Once cancelled, your cancellation request is recorded and processed by the airline operations team.",
            "- Support: If you need special assistance with group or medical cancellations, please contact airport passenger support.",
        ])

    # Check-in & Boarding FAQ
    if any(k in lower for k in ['check-in', 'check in time', 'boarding pass', 'when should i arrive', 'counter open', 'airport timing']):
        return "\n".join([
            "ARMS Airport Check-in & Boarding Information:",
            "- Domestic Flights: Airport check-in counters open 2 hours before scheduled departure and close 45 minutes prior.",
            "- International Flights: Counters open 3 hours before departure and close 60 minutes prior.",
            "- Boarding Gates: Gates open 45 minutes prior and close strictly 20 minutes before departure.",
            "- Required Documents: Valid government photo ID for domestic routes; Valid Passport & Visas for international routes.",
        ])

    return None


def get_travel_response(message, flights=None):
    # Check for direct FAQ or status queries first
    faq_response = _check_faq_or_flight_status(message)
    if faq_response:
        return faq_response

    prefs = extract_travel_preferences(message)
    budget = prefs.get('budget')
    days = prefs.get('days') or 3
    trip_type = prefs.get('trip_type', 'domestic')

    flights = flights or []
    flight_context = '\n'.join(
        f"{flight['code']}: {flight['from']} to {flight['to']}, "
        f"{flight['departure']}, economy {flight['currency']} {flight['economy_price']}"
        for flight in flights[:5]
    ) or 'No matching bookable flights were found in the ARMS database.'

    api_key = os.getenv("OPENAI_API_KEY")
    if api_key and OpenAI is not None:
        try:
            client = OpenAI(api_key=api_key)
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert AI travel assistant for the ARMS flight booking system. "
                            "Create practical travel plans from the traveler's budget, trip length, origin, destination, and style. "
                            "Use only real flights from the provided inventory; do not invent flight numbers. "
                            "Format flight references with links: [Book Seats](/seat_selection/<id>). "
                            "Include concise day-by-day itineraries and seasonal tips."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Request: {message}\n\nInventory:\n{flight_context}",
                    },
                ],
                max_tokens=600,
            )
            return completion.choices[0].message.content
        except Exception:
            pass

    recommendations = _build_local_recommendations(prefs)
    origin_label = prefs.get('origin') or 'Chennai (assumed; confirm your departure city)'
    budget_text = f"₹{int(budget):,}" if budget else "your stated budget"
    travel_label = 'international trip' if trip_type == 'international' else 'trip'
    lines = [
        f"{travel_label.title()} plan for {days} days, from {origin_label}. Budget: {budget_text} (estimates are per traveler unless you tell me otherwise).",
        "",
        "Best-fit destinations (indicative transport + lodging + daily spending; planning estimates, not live quotes):",
    ]
    for item in recommendations:
        budget_note = 'within budget' if item['within_budget'] else 'over budget'
        lines.append(
            f"- {item['name']}: about ₹{item['estimated_total']:,} total, {budget_note} "
            f"(estimated transport allowance ₹{item['flight_cost']:,}; lodging for {max(0, days - 1)} nights "
            f"~₹{item['hotel_cost']:,}; food/local transport/activities ~₹{item['daily_cost'] * days:,}). "
            f"{item['highlights']}"
        )

    if recommendations:
        chosen = recommendations[0]
        itinerary = _build_itinerary(chosen['name'], days, prefs.get('preferences', []))
        lines.extend(["", f"Suggested {chosen['name']} itinerary:"])
        lines.extend(f"- Day {index}: {activity}" for index, activity in enumerate(itinerary, 1))

    if prefs.get('month'):
        season_note = _seasonal_note(recommendations[0]['name'], prefs['month']) if recommendations else ''
        if season_note:
            lines.extend(["", f"Season note for {prefs['month']}: {season_note}"])

    lines.extend(["", "Bookable flights currently in the ARMS inventory:"])
    if flights:
        for flight in flights[:5]:
            flight_id = flight.get('id')
            book_link = f" [Book Seats](/seat_selection/{flight_id})" if flight_id else ""
            lines.append(
                f"- {flight['code']} | {flight['from']} to {flight['to']} | "
                f"{flight['departure']} | economy {flight['currency']} {flight['economy_price']} "
                f"({flight['economy_available']} seats shown available){book_link}"
            )
    else:
        lines.append("- No matching bookable flights were found. Try a different origin, destination, or date.")

    lines.extend([
        "",
        "These are planning estimates, not booking quotes. Tell me your departure city, exact dates, and number of travelers to narrow the plan.",
    ])
    return "\n".join(lines)


def _build_itinerary(destination, days, preferences):
    themes = {
        'Dubai': ['Old Dubai and souks', 'Desert safari or a beach afternoon', 'Downtown Dubai and the Museum of the Future'],
        'Bangkok': ['Grand Palace area and riverside temples', 'Market visit and Thai food walk', 'Choose a neighborhood, museum, or canal trip'],
        'Singapore': ['Marina Bay and Gardens by the Bay', 'Chinatown, Little India, and hawker food', 'Sentosa or a museum before departure'],
        'Bali': ['Ubud and nearby rice terraces', 'Temple visit and south-coast beach', 'Waterfall or relaxed local day'],
        'Paris': ['Central landmarks and Seine walk', 'Choose one major museum and explore its neighborhood', 'Montmartre and a relaxed cafe stop'],
        'Kuala Lumpur': ['City center and KLCC park', 'Batu Caves and local food streets', 'Heritage quarter and market visit'],
        'Colombo': ['Fort, Pettah market, and waterfront', 'Museum or temple visit and local food', 'Coastal neighborhood before departure'],
        'Kathmandu': ['Kathmandu Durbar Square and nearby lanes', 'Patan or Boudhanath', 'Swayambhu and a flexible city afternoon'],
        'Goa': ['Old Goa and Panaji', 'Choose a north or south beach area', 'Local market and a relaxed coastal afternoon'],
        'Hyderabad': ['Charminar and the old city', 'Golconda Fort and a local food stop', 'Museum or lakeside break'],
        'Delhi': ['Old Delhi and Jama Masjid area', 'Choose one major monument and nearby museum', 'Humayun’s Tomb or Lodhi Garden'],
        'Bangalore': ['Cubbon Park and central Bengaluru', 'Choose a food neighborhood and museum', 'Bengaluru Palace or a flexible local day'],
        'Jaipur': ['Amber Fort and the old city', 'City Palace and local markets', 'Hawa Mahal area and a food walk'],
        'Kochi': ['Fort Kochi and the waterfront', 'Mattancherry and local cafes', 'Flexible backwater or cultural visit'],
    }
    plan = themes.get(destination, [f'Explore {destination}’s central district and local food'] * 3)
    if preferences and 'beach destinations' in preferences and destination in ('Bangkok', 'Singapore'):
        plan[1] = 'Set aside the afternoon for a beach or waterfront visit'
    return [plan[min(index, len(plan) - 1)] for index in range(days)]


def _seasonal_note(destination, month):
    month_key = month.lower()
    best_periods = {
        'Dubai': 'November through March is generally more comfortable for outdoor activities.',
        'Bangkok': 'November through February is typically cooler and less rainy; check local advisories.',
        'Singapore': 'Expect warm, humid weather year-round; pack for brief rain showers.',
        'Bali': 'April through October is generally drier; check current local weather before booking.',
        'Paris': 'Spring and early autumn are often mild; summer is busier and winter is colder.',
        'Colombo': 'Conditions vary by coast; check the weather for your planned neighborhoods before booking.',
        'Kathmandu': 'Winter evenings can be cold; check mountain visibility and local conditions before day trips.',
        'Kuala Lumpur': 'Expect warm, humid weather year-round and plan for rain showers.',
    }
    if month_key in ('next month', 'this month'):
            month_key = (timezone.localdate().replace(day=1) if month_key == 'this month' else
                     (timezone.localdate().replace(day=1) + timedelta(days=32)).replace(day=1)).strftime('%B').lower()
    if destination == 'Singapore':
        return best_periods[destination]
    if destination in best_periods and destination != 'Singapore':
        return f"{best_periods[destination]} Verify forecasts and local advisories for {month}."
    return f"Check the local forecast, entry requirements, and seasonal opening hours for {destination} before booking {month}."
