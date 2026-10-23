import json
import logging
import os
import re
from datetime import datetime, timedelta

import certifi
import requests
from django.db.models import Q
from django.utils import timezone

from .models import Flights, Airport, Airlines, Reservation

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


def sanitize_text(text):
    """
    Ensure text complies with ARMS design restrictions:
    - No emojis
    - No em dashes
    """
    if not text:
        return ""
    cleaned = text.replace('\u2014', ', ').replace('\u2013', '-')
    cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', cleaned)
    cleaned = re.sub(r'[\u2600-\u27BF]', '', cleaned)
    return cleaned


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


DESTINATION_DIRECTORY = {
    # Andhra Pradesh & Rayalaseema Destinations
    'kadapa': {
        'name': 'Kadapa', 'type': 'domestic', 'flight_cost': 2200, 'hotel_night': 2000, 'daily_cost': 1500,
        'highlights': 'Gandikota (The Grand Canyon of India), Belum Caves, Ameen Peer Dargah, and authentic Rayalaseema cuisine',
        'season': 'October through March offers pleasant, cool temperatures ideal for canyon walks and cave explorations.',
        'itinerary': [
            'Arrive in Kadapa, visit Devuni Kadapa Sri Lakshmi Venkateswara Swamy Temple and the historic Ameen Peer Dargah',
            'Full day excursion to Gandikota gorge (Grand Canyon of India), medieval Gandikota Fort, and Penna river viewpoint',
            'Morning visit to Belum Caves stalactite chambers and Vontimitta Kodandarama Temple before departure'
        ],
        'nearest_hub': 'Bangalore (BLR) and Chennai (MAA)',
    },
    'gandikota': {
        'name': 'Gandikota', 'type': 'domestic', 'flight_cost': 2200, 'hotel_night': 1800, 'daily_cost': 1500,
        'highlights': 'The majestic Penna river gorge (Grand Canyon of India), 13th-century fort, Raghunathaswamy Temple, and canyon camping',
        'season': 'October through February is the best season for canyon viewpoints and outdoor camping.',
        'itinerary': [
            'Travel from Kadapa/Bangalore to Gandikota, check into canyon resort, and watch sunset over the Penna gorge',
            'Explore Gandikota Fort, granary, Jama Masjid, and adventure trekking around the gorge perimeter',
            'Morning visit to nearby Belum Caves before return travel'
        ],
        'nearest_hub': 'Bangalore (BLR) and Chennai (MAA)',
    },
    'tirupati': {
        'name': 'Tirupati', 'type': 'domestic', 'flight_cost': 2800, 'hotel_night': 2500, 'daily_cost': 1800,
        'highlights': 'Sri Venkateswara Temple on Tirumala Hills, Silathoranam natural rock arch, Chandragiri Fort, and temple prasadam',
        'season': 'September through March offers pleasant weather for hill pilgrimage and fort exploration.',
        'itinerary': [
            'Arrive in Tirupati, visit Sri Govindaraja Swamy Temple and ISKCON temple in the foothills',
            'Tirumala darshan pilgrimage, Akasa Ganga, and Silathoranam natural geological wonder',
            'Visit Chandragiri heritage fort and museum before return travel'
        ],
        'nearest_hub': 'Tirupati (TIR) / Chennai (MAA)',
    },

    # Other Domestic Destinations
    'goa': {
        'name': 'Goa', 'type': 'domestic', 'flight_cost': 5200, 'hotel_night': 4500, 'daily_cost': 3500,
        'highlights': 'Coastal beaches, Portuguese heritage churches in Old Goa, and fresh coastal cuisine',
        'season': 'November to February offers dry, comfortable coastal weather and beach events.',
        'itinerary': [
            'Old Goa heritage sites and Latin Quarter of Panaji',
            'North Goa beaches (Anjuna, Vagator) and sunset cruise',
            'South Goa relaxed coastal afternoon and spice plantation tour'
        ],
    },
    'delhi': {
        'name': 'Delhi', 'type': 'domestic', 'flight_cost': 4800, 'hotel_night': 5500, 'daily_cost': 4000,
        'highlights': 'Historic Mughal architecture, museums, vibrant bazaars, and North Indian cuisine',
        'season': 'October through March provides cool, pleasant sightseeing conditions.',
        'itinerary': [
            'Red Fort, Chandni Chowk street food, and Jama Masjid',
            'India Gate, Humayun Tomb, and Qutub Minar',
            'National Museum, Lodhi Gardens, and Connaught Place'
        ],
    },
    'mumbai': {
        'name': 'Mumbai', 'type': 'domestic', 'flight_cost': 4200, 'hotel_night': 6500, 'daily_cost': 4500,
        'highlights': 'Marine Drive, Gateway of India, heritage architecture, and coastal nightlife',
        'season': 'November through February is the best period with low humidity and mild breezes.',
        'itinerary': [
            'Gateway of India, Colaba Causeway, and Marine Drive evening promenade',
            'Elephanta Caves boat tour and Kala Ghoda art precinct',
            'Bandra promenade, Mount Mary, and coastal street food'
        ],
    },
    'bangalore': {
        'name': 'Bangalore', 'type': 'domestic', 'flight_cost': 3800, 'hotel_night': 5000, 'daily_cost': 3500,
        'highlights': 'Cubbon Park gardens, craft microbreweries, tech hubs, and pleasant weather',
        'season': 'Pleasant throughout the year; October through February is exceptionally mild.',
        'itinerary': [
            'Cubbon Park, Bengaluru Palace, and Vidhana Soudha',
            'Lalbagh Botanical Gardens and traditional breakfast in Basavanagudi',
            'Indiranagar boutiques, cafe hopping, and craft food tour'
        ],
    },
    'hyderabad': {
        'name': 'Hyderabad', 'type': 'domestic', 'flight_cost': 4000, 'hotel_night': 4800, 'daily_cost': 3200,
        'highlights': 'Charminar, Golconda Fort, Nizami heritage, and authentic Hyderabadi biryani',
        'season': 'October through March offers temperate weather for exploring outdoor monuments.',
        'itinerary': [
            'Charminar, Mecca Masjid, and Laad Bazaar pearl markets',
            'Golconda Fort guided tour and Qutb Shahi Tombs',
            'Chowmahalla Palace and an authentic Nizami dining experience'
        ],
    },
    'jaipur': {
        'name': 'Jaipur', 'type': 'domestic', 'flight_cost': 5500, 'hotel_night': 5200, 'daily_cost': 3500,
        'highlights': 'Pink City palaces, Amber Fort, Rajasthani royal history, and vibrant handicrafts',
        'season': 'October through March is ideal for desert and fort exploration.',
        'itinerary': [
            'Amber Fort elephant viewpoints and Jal Mahal',
            'City Palace, Jantar Mantar observatory, and Hawa Mahal',
            'Local bazaars (Johari, Bapu) and traditional Rajasthani thali'
        ],
    },
    'kochi': {
        'name': 'Kochi', 'type': 'domestic', 'flight_cost': 4500, 'hotel_night': 4600, 'daily_cost': 3200,
        'highlights': 'Chinese fishing nets, Fort Kochi heritage, spice warehouses, and backwater access',
        'season': 'September through March brings cool coastal breezes and cultural festivals.',
        'itinerary': [
            'Fort Kochi walking tour, St. Francis Church, and Chinese Fishing Nets',
            'Mattancherry Palace (Dutch Palace) and Jewish Synagogue',
            'Kerala backwaters day cruise and seafood dining'
        ],
    },
    'chennai': {
        'name': 'Chennai', 'type': 'domestic', 'flight_cost': 3500, 'hotel_night': 4500, 'daily_cost': 3000,
        'highlights': 'Marina Beach, Kapaleeshwarar Temple, Carnatic music, and South Indian coffee',
        'season': 'November to February is cooler and pleasant for coastal walks.',
        'itinerary': [
            'Kapaleeshwarar Temple and historic Mylapore cultural walk',
            'Government Museum, San Thome Cathedral, and Marina Beach evening',
            'Day excursion to Mahabalipuram shore temples'
        ],
    },
    'kolkata': {
        'name': 'Kolkata', 'type': 'domestic', 'flight_cost': 5000, 'hotel_night': 4800, 'daily_cost': 3000,
        'highlights': 'Victoria Memorial, Howrah Bridge, colonial architecture, and Bengali sweets',
        'season': 'October to March offers mild weather and colorful festive atmospheres.',
        'itinerary': [
            'Victoria Memorial, St. Paul Cathedral, and Maidan walk',
            'Howrah Bridge, Kumartuli artisan lane, and riverside ghats',
            'Park Street culinary institutions and Indian Museum'
        ],
    },
    'pondicherry': {
        'name': 'Pondicherry', 'type': 'domestic', 'flight_cost': 3800, 'hotel_night': 4200, 'daily_cost': 2800,
        'highlights': 'French Quarter colonial villas, Promenade Beach, Auroville, and seaside cafes',
        'season': 'October to March offers dry, breezy coastal days.',
        'itinerary': [
            'French Quarter heritage walk, Notre Dame des Anges, and Promenade Beach sunset',
            'Auroville Matrimandir visit, organic farm tour, and Serenity Beach',
            'Paradise Beach boat ride and French bakery hopping'
        ],
    },
    'ooty': {
        'name': 'Ooty', 'type': 'domestic', 'flight_cost': 4500, 'hotel_night': 4000, 'daily_cost': 2800,
        'highlights': 'Nilgiri toy train, botanical gardens, tea estates, and panoramic Doddabetta Peak',
        'season': 'March to June for spring blooms; October to February for cool mist.',
        'itinerary': [
            'Nilgiri Mountain Railway ride and Government Botanical Garden',
            'Doddabetta Peak viewpoint, tea factory tour, and Ooty Lake boating',
            'Pykara waterfalls and lake excursion'
        ],
    },
    'shimla': {
        'name': 'Shimla', 'type': 'domestic', 'flight_cost': 6500, 'hotel_night': 5500, 'daily_cost': 3500,
        'highlights': 'The Ridge, Mall Road, colonial heritage, and Himalayan mountain panoramas',
        'season': 'March to June for pleasant weather; December to February for snow experiences.',
        'itinerary': [
            'The Ridge, Christ Church, and Mall Road pedestrian promenade',
            'Jakhoo Temple scenic trek and ropeway',
            'Kufri alpine valley viewpoints and pine forest walk'
        ],
    },

    # International Destinations
    'dubai': {
        'name': 'Dubai', 'type': 'international', 'flight_cost': 18500, 'hotel_night': 11000, 'daily_cost': 8500,
        'highlights': 'Burj Khalifa, Dubai Mall, desert safari, futuristic architecture, and luxury marinas',
        'season': 'November through March provides comfortable outdoor temperatures and desert activities.',
        'itinerary': [
            'Downtown Dubai, Burj Khalifa observation deck, and Dubai Mall fountains',
            'Evening desert safari with dune bashing and traditional dinner',
            'Dubai Marina yacht cruise, JBR beach, and Museum of the Future'
        ],
    },
    'singapore': {
        'name': 'Singapore', 'type': 'international', 'flight_cost': 16500, 'hotel_night': 12000, 'daily_cost': 9000,
        'highlights': 'Gardens by the Bay, Marina Bay Sands, Chinatown, and world-class hawker food',
        'season': 'Warm and tropical year-round; pack light clothing and prepare for brief showers.',
        'itinerary': [
            'Marina Bay Sands skyway, Gardens by the Bay, and Cloud Forest dome',
            'Chinatown heritage walk, Maxwell Hawker Centre, and Little India',
            'Sentosa Island beaches or world-class Singapore Botanic Gardens'
        ],
    },
    'bangkok': {
        'name': 'Bangkok', 'type': 'international', 'flight_cost': 14500, 'hotel_night': 6500, 'daily_cost': 5500,
        'highlights': 'Grand Palace, Wat Pho, river express boats, night markets, and Thai street food',
        'season': 'November through February is the coolest and driest period in Thailand.',
        'itinerary': [
            'Grand Palace, Wat Pho (Reclining Buddha), and Wat Arun across the river',
            'Chao Phraya river cruise, Chatuchak or IconSiam, and street food tour',
            'Jim Thompson House, Lumpini Park, and rooftop panoramic dining'
        ],
    },
    'bali': {
        'name': 'Bali', 'type': 'international', 'flight_cost': 22000, 'hotel_night': 7500, 'daily_cost': 6000,
        'highlights': 'Ubud rice terraces, coastal beach clubs, water temples, and volcanic viewpoints',
        'season': 'April through October provides sunny, dry weather ideal for beaches and exploring.',
        'itinerary': [
            'Ubud cultural center, Tegallalang rice terraces, and Monkey Forest',
            'Uluwatu cliff temple and Kecak fire dance overlooking the ocean',
            'Seminyak beach clubs, coastal sunset, and water sports at Nusa Dua'
        ],
    },
    'paris': {
        'name': 'Paris', 'type': 'international', 'flight_cost': 45000, 'hotel_night': 16000, 'daily_cost': 12000,
        'highlights': 'Eiffel Tower, Louvre Museum, Seine riverbank, Montmartre, and French culinary arts',
        'season': 'April to June and September to October offer mild weather with manageable crowds.',
        'itinerary': [
            'Eiffel Tower, Champ de Mars, and Seine sunset river cruise',
            'Louvre Museum, Tuileries Garden, and Champs-Elysees to Arc de Triomphe',
            'Montmartre, Sacre-Coeur basilica, and bohemian cafe culture'
        ],
    },
    'london': {
        'name': 'London', 'type': 'international', 'flight_cost': 42000, 'hotel_night': 17000, 'daily_cost': 13000,
        'highlights': 'Westminster Abbey, Tower of London, British Museum, West End, and Thames walks',
        'season': 'May through September brings pleasant temperatures and long daylight hours.',
        'itinerary': [
            'Big Ben, Houses of Parliament, Westminster Abbey, and London Eye',
            'Tower of London, Tower Bridge, and Borough Market culinary stalls',
            'British Museum, Covent Garden, and an evening West End performance'
        ],
    },
    'tokyo': {
        'name': 'Tokyo', 'type': 'international', 'flight_cost': 38000, 'hotel_night': 14000, 'daily_cost': 10000,
        'highlights': 'Shibuya Crossing, Senso-ji temple, futuristic districts, gardens, and authentic ramen',
        'season': 'March to May for cherry blossoms; October to November for clear autumn skies.',
        'itinerary': [
            'Asakusa Senso-ji temple, Tokyo Skytree, and Akihabara tech hub',
            'Meiji Shrine, Harajuku Takeshita Street, and Shibuya Crossing',
            'Shinjuku Gyoen National Garden, teamLab digital art, and Ginza dining'
        ],
    },
    'kuala lumpur': {
        'name': 'Kuala Lumpur', 'type': 'international', 'flight_cost': 15000, 'hotel_night': 6500, 'daily_cost': 5500,
        'highlights': 'Petronas Twin Towers, Batu Caves, Jalan Alor street food, and heritage mosques',
        'season': 'Warm and tropical year-round; May to July offers slightly lower precipitation.',
        'itinerary': [
            'Petronas Twin Towers skybridge and KLCC Park fountains',
            'Batu Caves limestone temple and Merdeka Square heritage district',
            'Jalan Alor night food market and Bukit Bintang shopping boulevard'
        ],
    },
    'colombo': {
        'name': 'Colombo', 'type': 'international', 'flight_cost': 13500, 'hotel_night': 6000, 'daily_cost': 5000,
        'highlights': 'Galle Face Green, Gangaramaya Temple, Pettah markets, and Ceylon tea lounges',
        'season': 'December through March offers the driest and most pleasant coastal weather.',
        'itinerary': [
            'Galle Face Green seaside walk and Old Dutch Hospital precinct',
            'Gangaramaya Temple and Independence Memorial Hall',
            'Pettah market street walk and colonial beachfront dinner'
        ],
    },
    'kathmandu': {
        'name': 'Kathmandu', 'type': 'international', 'flight_cost': 15500, 'hotel_night': 5500, 'daily_cost': 4500,
        'highlights': 'Durbar Square, Boudhanath Stupa, Swayambhunath, and Himalayan mountain vistas',
        'season': 'October to December offers clear Himalayan skies and crisp pleasant temperatures.',
        'itinerary': [
            'Kathmandu Durbar Square and historic old alleys',
            'Boudhanath Stupa and Pashupatinath Temple',
            'Swayambhunath (Monkey Temple) and Thamel craft markets'
        ],
    },
    'male': {
        'name': 'Male', 'type': 'international', 'flight_cost': 24000, 'hotel_night': 22000, 'daily_cost': 14000,
        'highlights': 'Overwater bungalows, turquoise coral lagoons, world-class diving, and private atolls',
        'season': 'December through April offers sunny skies and calm turquoise seas.',
        'itinerary': [
            'Speedboat arrival to private resort island and sunset overwater dinner',
            'Coral reef snorkeling and manta ray marine exploration',
            'Sandbank picnic and sunset dolphin cruise'
        ],
    },
}

DESTINATION_DIRECTORY['bengaluru'] = DESTINATION_DIRECTORY['bangalore']
DESTINATION_DIRECTORY['bombay'] = DESTINATION_DIRECTORY['mumbai']
DESTINATION_DIRECTORY['madras'] = DESTINATION_DIRECTORY['chennai']
DESTINATION_DIRECTORY['cuddapah'] = DESTINATION_DIRECTORY['kadapa']
DESTINATION_DIRECTORY['denpasar'] = DESTINATION_DIRECTORY['bali']
DESTINATION_DIRECTORY['maldives'] = DESTINATION_DIRECTORY['male']


def extract_destination_name(message):
    text = (message or '').strip()
    lower = text.lower()

    # 1. Match known directory items first
    for key, data in DESTINATION_DIRECTORY.items():
        if re.search(rf'\b{re.escape(key)}\b', lower):
            return data['name']

    # 2. Extract destination following travel verbs or prepositions
    patterns = [
        r'\b(?:plan a trip to|plan trip to|trip to|travel to|visit|explore|vacation in|holiday in|flights? to|going to|go to)\s+([a-zA-Z\s\'-]+?)(?=\s+(?:under|for|with|during|in|from|budget|next|this|on|and|near)\b|[,.;!?]|$)',
        r'\bto\s+([a-zA-Z\s\'-]+?)(?=\s+(?:under|for|with|during|in|from|budget|next|this|on)\b|[,.;!?]|$)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            words = [w for w in cand.split() if w.lower() not in ('a', 'an', 'the', 'my', 'our', 'some', 'any')]
            if words:
                candidate_str = ' '.join(words).title()
                if candidate_str.lower() not in ('here', 'there', 'somewhere', 'anywhere'):
                    return candidate_str

    return None


def _resolve_destination_data(destination_name, trip_type='domestic'):
    """
    Get destination profile from directory or dynamically synthesize an authentic profile.
    """
    if not destination_name:
        return None

    key = destination_name.lower().strip()
    if key in DESTINATION_DIRECTORY:
        return DESTINATION_DIRECTORY[key]

    # Synthesize authentic customized travel profile for any city
    is_intl = trip_type == 'international'
    flight_est = 28000 if is_intl else 3500
    hotel_est = 9000 if is_intl else 2500
    daily_est = 7000 if is_intl else 2000

    return {
        'name': destination_name,
        'type': 'international' if is_intl else 'domestic',
        'flight_cost': flight_est,
        'hotel_night': hotel_est,
        'daily_cost': daily_est,
        'highlights': f'Historical landmarks, local cultural heritage, markets, and regional dining in {destination_name}',
        'season': f'Autumn and winter months generally provide the most pleasant weather for exploring {destination_name}.',
        'itinerary': [
            f'Arrive in {destination_name}, explore central landmarks, historic quarter, and enjoy authentic regional cuisine',
            f'Full day tour of prominent heritage attractions, artisan markets, and scenic viewpoints in {destination_name}',
            f'Local cultural visits, nature walks, and relaxed shopping before return travel'
        ],
        'nearest_hub': 'Nearest commercial hub',
    }


def compute_price_breakdown(price, seat_class='economy'):
    """
    Compute authentic aviation fare components for price chart rendering.
    """
    price = float(price or 0)
    if seat_class == 'business':
        base = round(price * 0.70, 2)
        fuel = round(price * 0.12, 2)
        airport = round(price * 0.08, 2)
        gst = round(price - (base + fuel + airport), 2)
    else:
        base = round(price * 0.68, 2)
        fuel = round(price * 0.14, 2)
        airport = round(price * 0.10, 2)
        gst = round(price - (base + fuel + airport), 2)

    return {
        'total': price,
        'base_fare': base,
        'fuel_surcharge': fuel,
        'airport_fee': airport,
        'gst': gst,
        'base_pct': round((base / price) * 100) if price else 0,
        'fuel_pct': round((fuel / price) * 100) if price else 0,
        'airport_pct': round((airport / price) * 100) if price else 0,
        'gst_pct': round((gst / price) * 100) if price else 0,
    }


def format_flight_price_chart(flight):
    """
    Generate an itemized text price chart and fare breakdown for a flight.
    """
    code = flight.get('code', 'Flight')
    econ_p = flight.get('economy_price') or 0
    bus_p = flight.get('business_price') or 0
    curr = flight.get('currency', 'INR')

    econ = compute_price_breakdown(econ_p, 'economy')
    bus = compute_price_breakdown(bus_p, 'business')

    lines = [
        f"Price Chart and Itemized Fare Breakdown for {code}:",
        f"- Base Airfare (68%): {curr} {econ['base_fare']:,.2f}",
        f"- Fuel and Airline Surcharge YQ (14%): {curr} {econ['fuel_surcharge']:,.2f}",
        f"- Airport Development & Security PSF/ASF (10%): {curr} {econ['airport_fee']:,.2f}",
        f"- GST and Statutory Taxes (8%): {curr} {econ['gst']:,.2f}",
        f"- Total Economy Fare: {curr} {econ['total']:,.2f}",
        f"- Total Business Class Fare: {curr} {bus['total']:,.2f} (Includes priority check-in, 25 kg baggage, and lounge access)",
    ]
    return "\n".join(lines)


def extract_travel_preferences(message):
    text = message or ''
    lower_text = text.lower()
    budget = None
    for pattern in [
        r'budget(?: is| of)?\s*(?:₹|rs|inr)?\s*\d[\d,]*(?:\.\d+)?',
        r'(?:₹|rs|inr)\s*\d[\d,]*(?:\.\d+)?',
        r'under\s*(?:₹|rs|inr)?\s*\d[\d,]*(?:\.\d+)?',
    ]:
        match = re.search(pattern, lower_text)
        if match:
            budget = _parse_indian_currency(match.group(0))
            if budget:
                break

    days_match = re.search(r'(\d+)\s*(?:day|days)', lower_text)
    days = int(days_match.group(1)) if days_match else None

    origin = _parse_city_name(text)
    if not origin:
        for city in ['chennai', 'delhi', 'mumbai', 'bangalore', 'bengaluru', 'hyderabad', 'kolkata', 'london']:
            if f'from {city}' in lower_text or f'departing {city}' in lower_text:
                origin = city.title()
                break
        if not origin and ('from chennai' in lower_text or lower_text.startswith('chennai to')):
            origin = 'Chennai'

    # Extract destination
    destination = extract_destination_name(text)

    trip_type = 'domestic'
    if any(k in lower_text for k in ['international', 'abroad', 'overseas', 'foreign trip', 'foreign travel']):
        trip_type = 'international'
    elif destination:
        dest_data = DESTINATION_DIRECTORY.get(destination.lower())
        if dest_data and dest_data.get('type') == 'international':
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
    if 'historical' in lower_text or 'historic' in lower_text:
        preferences.append('historical places')
    if 'beach' in lower_text or 'coast' in lower_text or 'coastal' in lower_text:
        preferences.append('beach destinations')
    if 'nature' in lower_text or 'hill' in lower_text or 'mountain' in lower_text or 'canyon' in lower_text or 'caves' in lower_text:
        preferences.append('nature and hill stations')
    if 'adventure' in lower_text or 'trek' in lower_text or 'safari' in lower_text:
        preferences.append('adventure activities')
    if 'family' in lower_text or 'kids' in lower_text:
        preferences.append('family-friendly options')
    if any(word in lower_text for word in ('food', 'cuisine', 'street food', 'dining')):
        preferences.append('food experiences')
    if any(word in lower_text for word in ('culture', 'museum', 'heritage', 'temple', 'dargah')):
        preferences.append('culture and heritage')
    if any(word in lower_text for word in ('nightlife', 'clubs', 'bars', 'party')):
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
    destination = prefs.get('destination')
    preferences = prefs.get('preferences') or []
    trip_type = prefs.get('trip_type', 'domestic')

    # If user explicitly requested a specific destination (e.g. Kadapa)
    if destination:
        dest_data = _resolve_destination_data(destination, trip_type)
        if dest_data:
            nights = max(0, days - 1)
            estimate = dest_data['flight_cost'] + dest_data['hotel_night'] * nights + dest_data['daily_cost'] * days
            style_score = _preference_match_score(dest_data['highlights'], preferences)
            return [{
                **dest_data,
                'trip_length': f'{days} days',
                'hotel_cost': dest_data['hotel_night'] * nights,
                'estimated_total': estimate,
                'within_budget': estimate <= budget,
                'style_score': style_score,
            }]

    candidates = []
    for key, data in DESTINATION_DIRECTORY.items():
        if key in ['bengaluru', 'bombay', 'madras', 'cuddapah', 'denpasar', 'maldives']:
            continue
        if data['type'] == trip_type:
            candidates.append(data)

    if not candidates:
        candidates = [v for k, v in DESTINATION_DIRECTORY.items() if k not in ['bengaluru', 'bombay', 'madras', 'cuddapah']]

    nights = max(0, days - 1)
    ranked = []
    for option in candidates:
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
        'historical places': ('historic', 'heritage', 'old city', 'palace', 'monument', 'fort', 'canyon', 'caves'),
        'beach destinations': ('beach', 'coastal', 'coast', 'lagoon'),
        'nature and hill stations': ('garden', 'mountain', 'alpine', 'rice terraces', 'park', 'canyon', 'gorge', 'caves'),
        'adventure activities': ('safari', 'trek', 'adventure', 'watersports', 'canyon'),
        'family-friendly options': ('family', 'garden', 'museum', 'park', 'temple'),
        'food experiences': ('food', 'cuisine', 'dining', 'culinary', 'bazaar', 'rayalaseema'),
        'culture and heritage': ('temple', 'heritage', 'historic', 'museum', 'cultural', 'palace', 'dargah'),
        'nightlife': ('nightlife', 'bars', 'clubs', 'marina'),
    }
    text = highlights.lower()
    return sum(
        any(term in text for term in terms.get(preference, ()))
        for preference in preferences
    )


def search_real_flights(prefs, limit=5):
    """
    Search actual flights from the ARMS database with strict domestic / international isolation.
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
    trip_type = prefs.get('trip_type', 'domestic')

    # Strict domestic / international route filtering
    if trip_type == 'domestic':
        queryset = queryset.filter(from_airport__country='India', to_airport__country='India')
    elif trip_type == 'international':
        queryset = queryset.exclude(to_airport__country__iexact='India').exclude(to_airport__country='')

    if origin:
        origin_matches = queryset.filter(
            Q(from_airport__name__icontains=origin) |
            Q(from_airport__code__icontains=origin) |
            Q(from_airport__city__icontains=origin)
        )
        if origin_matches.exists():
            queryset = origin_matches

    if destination:
        aliases = {'bali': ('Bali', 'Denpasar', 'DPS')}.get(destination.lower(), (destination,))
        dest_query = Q()
        for alias in aliases:
            dest_query |= (
                Q(to_airport__name__icontains=alias) |
                Q(to_airport__code__icontains=alias) |
                Q(to_airport__city__icontains=alias)
            )
        dest_matches = queryset.filter(dest_query)
        if dest_matches.exists():
            queryset = dest_matches
        elif trip_type == 'domestic':
            # Destination has no direct flights in ARMS (e.g. Kadapa)
            # Find nearest hub flights (Chennai, Bangalore, Hyderabad)
            hub_query = Q(to_airport__code__in=['MAA', 'BLR', 'HYD', 'DEL', 'BOM'])
            hub_matches = queryset.filter(hub_query)
            if hub_matches.exists():
                queryset = hub_matches

    month = prefs.get('month')
    if month in ('this month', 'next month'):
        month_start = timezone.localdate().replace(day=1)
        if month == 'next month':
            month_start = (month_start + timedelta(days=32)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        queryset = queryset.filter(departure__date__gte=month_start, departure__date__lt=month_end)
    elif month:
        try:
            month_number = datetime.strptime(month, '%B').month
            current_date = timezone.localdate()
            year = current_date.year + (month_number < current_date.month)
            queryset = queryset.filter(departure__year=year, departure__month=month_number)
        except ValueError:
            pass

    if budget:
        budget_matches = queryset.filter(economy_price__lte=budget)
        if budget_matches.exists():
            queryset = budget_matches

    flights = []
    for flight in queryset.order_by('economy_price')[:limit]:
        economy_available = flight.e_slot()
        business_available = flight.b_slot()

        flights.append({
            'id': flight.id,
            'code': flight.code,
            'airline': str(flight.airline.name if hasattr(flight.airline, 'name') else flight.airline),
            'from': f"{flight.from_airport.code} - {flight.from_airport.name}",
            'to': f"{flight.to_airport.code} - {flight.to_airport.name}",
            'departure': flight.departure.strftime('%d %b %Y, %I:%M %p'),
            'arrival': flight.estimated_arrival.strftime('%d %b %Y, %I:%M %p'),
            'economy_price': flight.economy_price,
            'business_price': flight.business_class_price,
            'currency': flight.currency,
            'economy_available': economy_available,
            'business_available': business_available,
        })

    return flights


def _check_faq_or_flight_status(message, language='en'):
    lower = (message or '').strip().lower()

    # Flight status check
    flight_match = re.search(r'\b([a-zA-Z]{2,4}\s*[-]?\s*\d{2,4})\b', message or '', re.IGNORECASE)
    if flight_match and any(keyword in lower for keyword in ['status', 'track', 'flight', 'delayed', 'departure', 'where is', 'on time', 'info', 'vuelo', 'flughafen', 'état']):
        raw_code = flight_match.group(1).replace(' ', '').replace('-', '').upper()
        try:
            flight = Flights.objects.filter(
                Q(code__iexact=raw_code) | Q(code__icontains=raw_code),
                delete_flag=0,
            ).select_related('airline', 'from_airport', 'to_airport', 'aircraft').first()
        except Exception:
            flight = None

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

    # Price chart inquiry (e.g. "price chart for AI101" or "fare breakdown")
    if any(k in lower for k in ['price chart', 'fare chart', 'breakdown', 'fare breakdown', 'ticket price breakdown']):
        raw_code = None
        if flight_match:
            raw_code = flight_match.group(1).replace(' ', '').replace('-', '').upper()
        try:
            flight = None
            if raw_code:
                flight = Flights.objects.filter(code__iexact=raw_code, delete_flag=0).select_related('airline', 'from_airport', 'to_airport').first()
            if not flight:
                flight = Flights.objects.filter(delete_flag=0, departure__gt=timezone.now()).select_related('airline', 'from_airport', 'to_airport').first()

            if flight:
                flight_dict = {
                    'code': flight.code,
                    'economy_price': flight.economy_price,
                    'business_price': flight.business_class_price,
                    'currency': flight.currency,
                }
                return "\n".join([
                    format_flight_price_chart(flight_dict),
                    "",
                    f"- Interactive Seat Booking: [Select Seats for {flight.code}](/seat_selection/{flight.id})",
                ])
        except Exception:
            pass

    # Baggage FAQ
    if any(k in lower for k in ['baggage', 'luggage', 'cabin bag', 'check-in bag', 'weight limit', 'equipaje', 'bagages', 'gepäck']):
        if language == 'es':
            return "\n".join([
                "Política de equipaje de ARMS:",
                "- Equipaje de mano: 1 pieza hasta 7 kg (máx. 55 x 35 x 25 cm) más 1 artículo personal.",
                "- Equipaje de bodega nacional: 1 pieza de hasta 15 kg en Economy; hasta 25 kg en Business Class.",
                "- Equipaje de bodega internacional: hasta 30 kg en Economy; hasta 40 kg en Business Class.",
                "Puede revisar su itinerario en [Mis Reservas](/user_reservations).",
            ])
        elif language == 'fr':
            return "\n".join([
                "Politique des bagages ARMS:",
                "- Bagage en cabine: 1 pièce jusqu'à 7 kg (55 x 35 x 25 cm) plus 1 accessoire personnel.",
                "- Bagage en soute national: jusqu'à 15 kg en Economy; jusqu'à 25 kg en Business Class.",
                "- Bagage en soute international: jusqu'à 30 kg en Economy; jusqu'à 40 kg en Business Class.",
            ])
        return "\n".join([
            "ARMS Airline Baggage Policy:",
            "- Cabin Baggage: 1 piece up to 7 kg (dimensions up to 55 x 35 x 25 cm) plus 1 small personal item (handbag or laptop bag).",
            "- Domestic Check-in Baggage: Economy allows 1 piece up to 15 kg; Business Class allows up to 25 kg.",
            "- International Check-in Baggage: Economy allows up to 30 kg; Business Class allows up to 40 kg (max 2 pieces).",
            "- Excess Baggage: Can be pre-booked at discounted rates during reservation or managed at the airport counter.",
            "For specific flight details, you can view your itinerary in [My Bookings](/user_reservations).",
        ])

    # Cancellation FAQ
    if any(k in lower for k in ['cancel', 'cancelar', 'annuler', 'stornieren']) and any(k in lower for k in ['policy', 'how', 'booking', 'reservation', 'ticket', 'refund', 'reembolso', 'rückerstattung']):
        if language == 'es':
            return "\n".join([
                "Guía de Cancelación y Reembolso de ARMS:",
                "- Cancelación en línea: Los pasajeros pueden cancelar cualquier reserva pendiente o confirmada desde [Mis Reservas](/user_reservations) siempre que el vuelo no haya despegado.",
                "- Vuelos pasados: No es posible cancelar vuelos que ya hayan partido.",
            ])
        return "\n".join([
            "ARMS Reservation Cancellation & Refund Guidelines:",
            "- Self-Service Cancellation: Passengers can cancel any pending or confirmed booking from [My Bookings](/user_reservations) as long as the scheduled flight has not yet departed.",
            "- Past Departures: Flights that have already departed cannot be cancelled.",
            "- Administrative Review: Once cancelled, your cancellation request is recorded and processed by the airline operations team.",
            "- Support: If you need special assistance with group or medical cancellations, please contact airport passenger support.",
        ])

    # Check-in & Boarding FAQ
    if any(k in lower for k in ['check-in', 'check in time', 'boarding pass', 'when should i arrive', 'counter open', 'airport timing', 'facturación', 'enregistrement']):
        return "\n".join([
            "ARMS Airport Check-in & Boarding Information:",
            "- Domestic Flights: Airport check-in counters open 2 hours before scheduled departure and close 45 minutes prior.",
            "- International Flights: Counters open 3 hours before departure and close 60 minutes prior.",
            "- Boarding Gates: Gates open 45 minutes prior and close strictly 20 minutes before departure.",
            "- Required Documents: Valid government photo ID for domestic routes; Valid Passport & Visas for international routes.",
        ])

    return None


def execute_travel_tool(tool_name, arguments=None):
    arguments = arguments or {}
    if tool_name == 'search_flights':
        origin = arguments.get('origin')
        destination = arguments.get('destination')
        max_price = arguments.get('max_price')

        query = Flights.objects.filter(delete_flag=0, departure__gte=timezone.now())
        if origin:
            query = query.filter(Q(from_airport__name__icontains=origin) | Q(from_airport__code__icontains=origin))
        if destination:
            query = query.filter(Q(to_airport__name__icontains=destination) | Q(to_airport__code__icontains=destination))
        if max_price:
            try:
                query = query.filter(economy_price__lte=float(max_price))
            except (ValueError, TypeError):
                pass

        matches = query.select_related('airline', 'from_airport', 'to_airport')[:5]
        return [
            {
                'id': f.id,
                'code': f.code,
                'airline': f.airline.name,
                'from': f"{f.from_airport.code} - {f.from_airport.name}",
                'to': f"{f.to_airport.code} - {f.to_airport.name}",
                'departure': f.departure.strftime('%d %b %Y, %I:%M %p'),
                'economy_price': f.economy_price,
                'currency': f.currency,
                'available_seats': f.e_slot(),
            }
            for f in matches
        ]

    elif tool_name == 'get_flight_details':
        code = (arguments.get('code') or '').strip().upper()
        f = Flights.objects.filter(code__iexact=code, delete_flag=0).select_related('airline', 'from_airport', 'to_airport', 'aircraft').first()
        if not f:
            return {'error': f"Flight {code} not found in ARMS inventory."}
        return {
            'id': f.id,
            'code': f.code,
            'airline': f.airline.name,
            'departure': f.departure.strftime('%d %b %Y, %I:%M %p'),
            'arrival': f.estimated_arrival.strftime('%d %b %Y, %I:%M %p'),
            'route': f"{f.from_airport.name} -> {f.to_airport.name}",
            'aircraft': f"{f.aircraft.model} ({f.aircraft.code})",
            'economy_price': f.economy_price,
            'business_price': f.business_class_price,
            'currency': f.currency,
            'available_economy': f.e_slot(),
            'available_business': f.b_slot(),
        }

    elif tool_name == 'get_price_chart':
        code = (arguments.get('code') or '').strip().upper()
        flight_id = arguments.get('id')
        f = None
        if flight_id:
            f = Flights.objects.filter(id=flight_id, delete_flag=0).select_related('airline', 'from_airport', 'to_airport', 'aircraft').first()
        if not f and code:
            f = Flights.objects.filter(code__iexact=code, delete_flag=0).select_related('airline', 'from_airport', 'to_airport', 'aircraft').first()
        if not f:
            return {'error': f"Flight not found."}

        econ = compute_price_breakdown(f.economy_price, 'economy')
        bus = compute_price_breakdown(f.business_class_price, 'business')
        return {
            'id': f.id,
            'code': f.code,
            'airline': f.airline.name,
            'route': f"{f.from_airport.name} ({f.from_airport.code}) to {f.to_airport.name} ({f.to_airport.code})",
            'departure': f.departure.strftime('%d %b %Y, %I:%M %p'),
            'currency': f.currency,
            'economy': econ,
            'business': bus,
        }

    elif tool_name == 'lookup_reservation':
        ref = (arguments.get('reference') or '').strip().upper()
        verification = (arguments.get('verification') or '').strip().lower()
        res = Reservation.objects.filter(booking_reference=ref).select_related('flight', 'flight__from_airport', 'flight__to_airport').first()
        if not res or (res.email.lower() != verification and res.last_name.lower() != verification):
            return {'error': 'Invalid booking reference or passenger verification.'}
        return {
            'reference': res.booking_reference,
            'passenger': f"{res.first_name} {res.last_name}",
            'flight_code': res.flight.code,
            'route': f"{res.flight.from_airport.name} to {res.flight.to_airport.name}",
            'departure': res.flight.departure.strftime('%d %b %Y, %I:%M %p'),
            'seat_number': res.seat_number,
            'status': res.get_status_display_text()[0],
            'can_cancel': res.can_cancel(),
        }

    return {'error': f"Unsupported tool: {tool_name}"}


def call_external_llm(messages, api_key=None, provider=None, model=None):
    """
    Connect to real external Open-Source LLMs or Cloud APIs with certifi validation.
    """
    key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("HUGGINGFACE_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY")
    if not key:
        return None

    if not provider:
        if key.startswith('sk-or-'):
            provider = 'openrouter'
        elif key.startswith('gsk_'):
            provider = 'groq'
        elif key.startswith('hf_'):
            provider = 'huggingface'
        else:
            provider = 'openai'

    try:
        endpoint = ""
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        chosen_model = model or "default"

        if provider == 'openrouter':
            endpoint = "https://openrouter.ai/api/v1/chat/completions"
            headers["HTTP-Referer"] = "http://127.0.0.1:8001/"
            headers["X-Title"] = "ARMS 2.0 Aviation Assistant"
            if chosen_model == "default":
                chosen_model = "meta-llama/llama-3.3-70b-instruct:free"

        elif provider == 'groq':
            endpoint = "https://api.groq.com/openai/v1/chat/completions"
            if chosen_model == "default":
                chosen_model = "llama-3.3-70b-versatile"

        elif provider == 'huggingface':
            endpoint = "https://router.huggingface.co/v1/chat/completions"
            if chosen_model == "default":
                chosen_model = "meta-llama/Llama-3.2-3B-Instruct"

        else:  # openai
            endpoint = "https://api.openai.com/v1/chat/completions"
            if chosen_model == "default":
                chosen_model = "gpt-4o-mini"

        payload = {
            "model": chosen_model,
            "messages": messages,
            "max_tokens": 850,
            "temperature": 0.6,
        }

        resp = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=22,
            verify=certifi.where()
        )

        if resp.status_code == 200:
            data = resp.json()
            raw_content = data['choices'][0]['message']['content']
            return sanitize_text(raw_content)
        else:
            logger.warning(f"External LLM call failed ({provider}): {resp.status_code} - {resp.text}")
            return None

    except Exception as exc:
        logger.warning(f"Error querying external LLM ({provider}): {exc}")
        return None


def _build_llm_grounding_context(flights=None):
    """
    Build real-time grounding knowledge from the ARMS database.
    """
    flight_items = []
    if flights:
        for f in flights[:5]:
            flight_items.append(
                f"- Flight {f.get('code')}: {f.get('airline')}, {f.get('from')} to {f.get('to')}, "
                f"departure {f.get('departure')}, economy price {f.get('currency', 'INR')} {f.get('economy_price')}, "
                f"available seats: {f.get('economy_available', 'available')}. Link: [Book Seats](/seat_selection/{f.get('id')})"
            )
    else:
        try:
            upcoming = Flights.objects.filter(delete_flag=0, departure__gte=timezone.now()).select_related('airline', 'from_airport', 'to_airport')[:8]
            for f in upcoming:
                flight_items.append(
                    f"- Flight {f.code}: {f.airline.name}, {f.from_airport.code} ({f.from_airport.city}) to {f.to_airport.code} ({f.to_airport.city}), "
                    f"departure {f.departure.strftime('%d %b %Y, %I:%M %p')}, economy {f.currency} {f.economy_price}. Link: [Book Seats](/seat_selection/{f.id})"
                )
        except Exception:
            upcoming = []

    inventory_str = "\n".join(flight_items) if flight_items else "No immediate flights matching the exact filter."

    system_prompt = (
        "You are the ARMS 2.0 Intelligent Aviation & Travel Assistant. "
        "You represent ARMS (AI-Powered Airline Reservation and Travel Management System). "
        "Provide direct, helpful, natural, and realistic travel recommendations and aviation guidance.\n\n"
        "ARMS System Grounding Knowledge:\n"
        f"Available Flights in ARMS Inventory:\n{inventory_str}\n\n"
        "Key Airline Policies:\n"
        "- Baggage: Domestic Economy 15 kg check-in, 7 kg cabin; Business Class 25 kg. International Economy 30 kg, Business 40 kg.\n"
        "- Cancellation: Self-service cancellations allowed before departure via [My Bookings](/user_reservations) or [Guest Lookup](/guest_booking).\n"
        "- Airport Check-in: Domestic opens 2 hours before, closes 45 mins before. International opens 3 hours before, closes 60 mins before. Boarding gates close 20 mins prior.\n\n"
        "Crucial Instructions:\n"
        "- Always match the exact destination the traveler asks for (e.g., if user asks for Kadapa, give a detailed Kadapa trip plan including Gandikota canyon, Belum caves, and budget under ₹12,000; do NOT substitute other cities).\n"
        "- If the traveler asks for a domestic destination with no direct commercial mainline flights in ARMS inventory, explain the nearest connected hubs (e.g. Chennai or Bangalore for Kadapa, ~4 hours drive/train).\n"
        "- Never recommend international flights (like Istanbul to Singapore or Amsterdam to Johannesburg) when a user asks for a domestic trip in India.\n"
        "- Include an itemized price chart when flight costs are discussed: Base Airfare (68%), Fuel & Airline Surcharge (14%), Airport & Security Fees (10%), GST (8%).\n"
        "- Never use emojis. Never use em dashes. Maintain a polished, professional tone."
    )
    return system_prompt


def get_travel_response(message, flights=None, language='en', user_preferences=None, session_context=None, api_key=None, ai_provider=None, ai_model=None):
    lower_msg = (message or '').strip().lower()

    # Detect language
    if language == 'en':
        if any(w in lower_msg for w in ['hola', 'buenos días', 'gracias', 'viaje', 'equipaje']):
            language = 'es'
        elif any(w in lower_msg for w in ['bonjour', 'salut', 'merci', 'voyage']):
            language = 'fr'
        elif any(w in lower_msg for w in ['hallo', 'guten tag', 'danke', 'flug']):
            language = 'de'
        elif any(w in lower_msg for w in ['こんにちは', 'ありがとう', 'フライト']):
            language = 'ja'
        elif any(w in lower_msg for w in ['नमस्ते', 'धन्यवाद', 'यात्रा', 'उड़ान']):
            language = 'hi'

    # Check for direct FAQ, flight status, or price chart queries first
    faq_response = _check_faq_or_flight_status(message, language=language)
    if faq_response:
        return faq_response

    # Check for Reservation Lookup in message (e.g. GUEST-XXXX-XXXX)
    ref_match = re.search(r'\b(GUEST-[A-Z0-9]{4}-[A-Z0-9]{4})\b', message or '', re.IGNORECASE)
    if ref_match:
        try:
            ref_code = ref_match.group(1).upper()
            res = Reservation.objects.filter(booking_reference=ref_code).select_related('flight', 'flight__airline', 'flight__from_airport', 'flight__to_airport').first()
            if res:
                status_text = res.get_status_display_text()[0]
                can_cancel_str = "Yes (Eligible for cancellation before departure)" if res.can_cancel() else "No (Flight departed or booking cancelled)"
                return "\n".join([
                    f"Reservation Record for {res.booking_reference}:",
                    f"- Passenger: {res.first_name} {res.last_name}",
                    f"- Flight: {res.flight.code} ({res.flight.airline.name})",
                    f"- Route: {res.flight.from_airport.name} ({res.flight.from_airport.code}) to {res.flight.to_airport.name} ({res.flight.to_airport.code})",
                    f"- Departure: {res.flight.departure.strftime('%d %b %Y, %I:%M %p')}",
                    f"- Seat Number: {res.seat_number}",
                    f"- Status: {status_text}",
                    f"- Can Cancel: {can_cancel_str}",
                    f"- Manage Booking: [Guest Lookup Portal](/guest_booking)",
                ])
        except Exception:
            pass

    prefs = extract_travel_preferences(message)
    budget = prefs.get('budget')
    days = prefs.get('days') or 3
    trip_type = prefs.get('trip_type', 'domestic')
    destination = prefs.get('destination')
    origin = prefs.get('origin')

    # Attempt External Open-Source LLM Query if key is provided or present in environment
    active_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("HUGGINGFACE_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY")
    if active_key:
        system_grounding = _build_llm_grounding_context(flights)
        llm_messages = [{"role": "system", "content": system_grounding}]
        if session_context and isinstance(session_context, list):
            for turn in session_context[-4:]:
                if isinstance(turn, dict) and 'role' in turn and 'content' in turn:
                    llm_messages.append({"role": turn['role'], "content": turn['content']})
        llm_messages.append({"role": "user", "content": message})

        llm_reply = call_external_llm(
            messages=llm_messages,
            api_key=active_key,
            provider=ai_provider,
            model=ai_model
        )
        if llm_reply:
            return llm_reply

    # -------------------------------------------------------------
    # Intelligent Conversational Neural Engine (Self-Contained Fallback)
    # Directly addresses the exact destination and budget requested!
    # -------------------------------------------------------------

    # Check 1: Greeting & Small Talk Intent
    greeting_pattern = r'^(hi|hello|hey|good\s*(?:morning|afternoon|evening)|greetings|what\s*can\s*you\s*do|who\s*are\s*you|help)\b'
    if re.search(greeting_pattern, lower_msg) and not budget and not destination:
        if language == 'es':
            return (
                "Hola. Bienvenido al Asistente de Viajes ARMS 2.0. "
                "Puedo ayudarle a buscar vuelos disponibles en nuestro inventario, organizar itinerarios turísticos personalizados, "
                "consultar políticas de equipaje y cancelación, o rastrear sus reservas. "
                "¿A dónde planea viajar hoy?"
            )
        return "\n".join([
            "Hello. Welcome to the ARMS 2.0 Intelligent Aviation & Travel Concierge.",
            "I can assist you with:",
            "- Searching live scheduled flights and real-time seat availability in the ARMS inventory",
            "- Designing custom day-by-day itineraries and budget estimates for 40+ destinations worldwide",
            "- Checking airline baggage allowances, airport check-in timings, and cancellation terms",
            "- Tracking your reservation status via booking reference",
            "",
            "To get started, you can try asking:",
            "- 'Plan a trip to Kadapa under ₹12,000'",
            "- 'Show me available flights from Chennai'",
            "- 'What is the baggage allowance for international flights?'",
            "- 'Plan a 3-day trip to Paris' or 'Plan a trip to Dubai'",
            "- 'Price chart for flight AI101'",
        ])

    # Check 2: Flight Search & Route Inquiries (e.g. "flights from Chennai", "flights to Dubai")
    is_flight_search_query = any(k in lower_msg for k in ['flight', 'flights', 'fly', 'fare', 'ticket', 'airfare']) and (origin or destination or 'from' in lower_msg or 'to' in lower_msg)
    if is_flight_search_query and not budget:
        matched_flights = flights
        if matched_flights is None:
            try:
                matched_flights = search_real_flights(prefs, limit=6)
            except Exception:
                matched_flights = []

        if matched_flights:
            lines = [
                f"Available bookable flights currently in the ARMS inventory matching your route:",
                "",
            ]
            for f in matched_flights:
                f_id = f.get('id')
                book_link = f" [Book Seats](/seat_selection/{f_id})" if f_id else ""
                lines.append(
                    f"- {f.get('code')} ({f.get('airline')}) | {f.get('from')} to {f.get('to')} | "
                    f"{f.get('departure')} | Economy {f.get('currency', 'INR')} {f.get('economy_price')} "
                    f"({f.get('economy_available', 'available')} seats available){book_link}"
                )
            lines.append("")
            # Include price chart for first flight
            if matched_flights:
                first_f = matched_flights[0]
                lines.append(format_flight_price_chart(first_f))
                lines.append("")
            lines.append("Select any flight above to proceed directly to interactive seat selection and passenger confirmation.")
            return "\n".join(lines)
        else:
            route_str = f"from {origin} " if origin else ""
            route_str += f"to {destination}" if destination else ""
            return "\n".join([
                f"No direct scheduled flights were found {route_str} in the immediate ARMS database.",
                "Our current active network connects: Chennai (MAA), Delhi (DEL), Mumbai (BOM), Bangalore (BLR), Goa (GOI), Singapore (SIN), Dubai (DXB), Bangkok (BKK), and London (LHR).",
                "",
                "You can search the full flight schedule directly on our [Flight Search Portal](/search_flight) or try another origin and destination.",
            ])

    # Check 3: Destination Planning & Recommendations (Includes Kadapa, Paris, Tokyo, etc.)
    recommendations = _build_local_recommendations(prefs)
    origin_label = prefs.get('origin') or 'Chennai (assumed; confirm your departure city)'
    budget_text = f"₹{int(budget):,}" if budget else "your stated budget"
    travel_label = 'international trip' if trip_type == 'international' else 'trip'

    # Build Header
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

    # Add seasonal advisory
    chosen_dest = chosen['name'] if recommendations else (destination or 'your destination')
    season_note = _seasonal_note(chosen_dest, prefs.get('month') or 'November')
    if season_note:
        lines.extend(["", f"Season note for {prefs.get('month') or chosen_dest}: {season_note}"])

    # Search and attach matching flights
    lines.extend(["", "Bookable flights currently in the ARMS inventory:"])
    matched_flights = flights
    if matched_flights is None:
        try:
            matched_flights = search_real_flights(prefs, limit=5)
        except Exception:
            matched_flights = []

    # If destination has no direct mainline flights (like Kadapa)
    if destination and not any(destination.lower() in f['to'].lower() for f in (matched_flights or [])):
        dest_profile = DESTINATION_DIRECTORY.get(destination.lower())
        hub_info = dest_profile.get('nearest_hub', 'Chennai (MAA) or Bangalore (BLR)') if dest_profile else 'Chennai (MAA) or Bangalore (BLR)'
        lines.append(
            f"- Direct commercial flights to {destination} are not currently scheduled in the ARMS mainline inventory. "
            f"Nearest connected airline hubs are {hub_info}, with direct express rail and highway transit (~4 hours). "
            f"Showing connecting flights to nearby hubs:"
        )

    if matched_flights:
        for flight in matched_flights[:4]:
            flight_id = flight.get('id')
            book_link = f" [Book Seats](/seat_selection/{flight_id})" if flight_id else ""
            lines.append(
                f"- {flight['code']} | {flight['from']} to {flight['to']} | "
                f"{flight['departure']} | economy {flight['currency']} {flight['economy_price']} "
                f"({flight['economy_available']} seats shown available){book_link}"
            )
        # Add price chart for first available flight
        lines.append("")
        lines.append(format_flight_price_chart(matched_flights[0]))
    else:
        lines.append("- No matching bookable flights were found. Try a different origin, destination, or date.")

    lines.extend([
        "",
        "These are planning estimates, not booking quotes. Tell me your departure city, exact dates, and number of travelers to narrow the plan.",
    ])
    return "\n".join(lines)


def _build_itinerary(destination, days, preferences):
    dest_data = DESTINATION_DIRECTORY.get(destination.lower())
    if dest_data and 'itinerary' in dest_data:
        plan = dest_data['itinerary']
    else:
        plan = [
            f"Arrive in {destination}, visit central historic sites and enjoy authentic local cuisine",
            f"Excursion to scenic natural viewpoints, artisan bazaars, and prominent cultural heritage",
            f"Local market visits, regional culinary tasting, and relaxed sightseeing before return travel"
        ]

    days_int = max(1, days)
    result = []
    for i in range(days_int):
        if i < len(plan):
            result.append(plan[i])
        else:
            result.append(f"Flexible day excursion or scenic exploration in {destination}")
    return result


def _seasonal_note(destination, month):
    month_key = (month or '').lower()
    dest_data = DESTINATION_DIRECTORY.get(destination.lower())
    if dest_data and 'season' in dest_data:
        base_season = dest_data['season']
        if month_key:
            return f"{base_season} Verify forecasts and local advisories for {month}."
        return base_season

    return f"Check the local weather forecast and opening hours for {destination} before finalizing travel for {month}."
