import requests                     # Library om HTTP-verzoeken te versturen
from requests.auth import HTTPBasicAuth   # Voor Basic Authentication met API key
from datetime import datetime, timedelta  # Voor datum- en tijdberekeningen
from dotenv import load_dotenv            # Laadt variabelen uit een .env bestand
import os                                # OS-functionaliteit (omgeving, paden)

# Dynamische lijst waarin de UI/CLI de gekozen workouts plaatst
WORKOUTS = []


# ==========================
# LOAD ENV
# ==========================

load_dotenv()   # Laad alle sleutel/waardes uit het .env bestand in omgeving

API_KEY = os.getenv("INTERVALS_API_KEY")  # Haalt API key voor Intervals.icu op
BASE_URL = "https://intervals.icu"        # Basis-URL voor API requests

# Bepaalt of we API key authenticatie moeten gebruiken
USE_API_KEY = True if API_KEY else False

# Standaard instellingen
DEFAULT_START_TIME = "18:00:00"          # Default startuur van workout
UPSERT_ON_UID = False                    # Geen automatische update op UID
UPDATE_PLAN_APPLIED = True               # Pas plan-updates toe bij push


# ==========================
# ATHLETE ID HANDLING
# ==========================

def get_athlete_id():
    """
    Haalt ALTIJD de huidige geselecteerde ATHLETE_ID op
    uit de environment variabelen.

    Hierdoor werkt het dynamisch selecteren van atleten
    in jouw CLI.
    """
    return os.getenv("ATHLETE_ID")


# ==========================
# AUTH HELPERS
# ==========================

def get_auth():
    """
    Geeft BasicAuth terug indien API_KEY actief is.
    Anders None, want Intervals.icu API keys gebruiken BasicAuth
    en geen Bearer tokens.
    """
    if USE_API_KEY:
        return HTTPBasicAuth("API_KEY", API_KEY)
    return None


def get_headers():
    """
    Geeft altijd JSON headers terug.
    Authenticatie gebeurt via BasicAuth in requests, niet in headers.
    """
    return {"Content-Type": "application/json"}


# ==========================
# WORKOUT → EVENT BUILDER
# ==========================

def build_event_from_workout(w):
    """
    Zet één workout-dict om naar een event payload
    die voldoet aan de Intervals.icu API structuur.

    - Combineert datum + standaard starttijd
    - Berekening einde
    - Verplicht velden conform API
    """

    # Bouw startdatetime (ISO 8601)
    start = datetime.fromisoformat(f"{w['date']}T{DEFAULT_START_TIME}")

    # Eindtijd gebaseerd op duur
    end = start + timedelta(minutes=w["duration_minutes"])

    # Category correct instellen:
    #  - indien workout een eigen category heeft → gebruik die
    #  - anders → verplicht "WORKOUT"
    category = w.get("category", "WORKOUT")

    # API accepteert GEEN unicode dashes → alles ASCII maken
    safe_name = w["name"].replace("–", "-").replace("—", "-")
    safe_description = w["description"].replace("–", "-").replace("—", "-")

    return {
        "start_date_local": start.isoformat(),        # Start in ISO
        "end_date_local": end.isoformat(),            # Eindtijd
        "name": safe_name,                            # ASCII-only naam
        "description": safe_description,              # ASCII-only omschrijving
        "category": category,                         # VERPLICHT veld!
        "type": "Run",                                # Sporttype
        "moving_time": w["duration_minutes"] * 60,    # Totale actieve tijd in seconden
        "indoor": False                               # Altijd outdoor
    }


# ==========================
# PUSH WORKOUTS
# ==========================

def push_workouts_to_intervals():
    """
    Stuurt ALLE workouts uit WORKOUTS naar de Intervals.icu API
    als bulk-insert.

    - Haalt dynamisch gekozen athlete_id op
    - Stelt juiste URL & query parameters in
    - Bouwt event payloads
    - Voert POST request uit
    """

    athlete_id = get_athlete_id()  # Altijd de meest recente selectie uit CLI

    url = f"{BASE_URL}/api/v1/athlete/{athlete_id}/events/bulk"  # Bulk API endpoint

    # Query parameters voor API gedrag
    params = {
        "upsert": False,
        "upsertOnUid": UPSERT_ON_UID,
        "updatePlanApplied": UPDATE_PLAN_APPLIED
    }

    # Bouw alle afzonderlijke workouts om naar event dicts
    events = [build_event_from_workout(w) for w in WORKOUTS]

    # Voer request uit
    response = requests.post(
        url,
        json=events,        # JSON payload met lijst van events
        params=params,      # Query parameters
        headers=get_headers(), # Content-Type
        auth=get_auth(),    # BasicAuth of None
        timeout=30,         # Time-out om vastlopen te voorkomen
    )

    print("Status:", response.status_code)

    # Toon zo mogelijk de JSON response
    try:
        print(response.json())
    except:
        print(response.text)  # Fallback voor niet-JSON

    return response
