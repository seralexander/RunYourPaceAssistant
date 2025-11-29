import requests  # Importeert de requests-library om HTTP-verzoeken uit te voeren
from requests.auth import HTTPBasicAuth  # Importeert Basic Authentication helper
from datetime import datetime, timedelta  # Importeert datums en tijdsduur-functionaliteit
from dotenv import load_dotenv  # Importeert functie om .env-bestanden in te laden
import os  # Importeert OS-module voor omgevingsvariabelen
from Workouts.MarathonGentSeb import WORKOUTS  # Importeert een lijst/structuur met workouts uit een aparte file

# ==========================
# LOAD ENV
# ==========================

load_dotenv()  # Laadt alle variabelen uit het .env bestand in het systeem
API_KEY = os.getenv("INTERVALS_API_KEY")  # Haalt API key op uit de omgeving
ATHLETE_ID = os.getenv("ATHLETE_ID")  # Haalt Intervals.icu athlete ID op
BASE_URL = "https://intervals.icu"  # Basis URL van de Intervals.icu API

USE_API_KEY = True if API_KEY else False  # Bepaalt of authentificatie via API key gebruikt wordt

DEFAULT_START_TIME = "18:00:00"  # Standaard startuur voor de workouts indien niet aanwezig
UPSERT_ON_UID = False  # Bepaalt of workouts vervangen worden op basis van uid
UPDATE_PLAN_APPLIED = True  # Bepaalt of updates doorgevoerd worden op het trainingsplan


# ==========================
# AUTH HELPERS
# ==========================

def get_auth():
    if USE_API_KEY:  # Controleert of API key mode actief is
        return HTTPBasicAuth("API_KEY", API_KEY)  # Stelt BasicAuth in met 'API_KEY' als username
    return None  # Zoniet, geen auth meegeven (of via header geregeld)


def get_headers():
    if USE_API_KEY:  # Bij API key auth gebruik je enkel Content-Type
        return {"Content-Type": "application/json"}
    return {  # Anders Bearer token auth gebruiken
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }


# ==========================
# WORKOUT → EVENT BUILDER
# ==========================

def build_event_from_workout(w):
    # Zet workoutdatum + standaard starttijd om naar datetime object
    start = datetime.fromisoformat(f"{w['date']}T{DEFAULT_START_TIME}")

    # Einde berekenen op basis van de duur van de workout
    end = start + timedelta(minutes=w["duration_minutes"])

    return {
        "start_date_local": start.isoformat(),  # Starttijd in ISO formaat
        "end_date_local": end.isoformat(),  # Eindtijd in ISO formaat
        "name": w["name"],  # Naam van de workout
        "description": w["description"],  # Omschrijving van de workout
        "category": w.get("category", "WORKOUT"),  # Type event, standaard WORKOUT
        "type": "Run",  # Type sportactiviteit
        "moving_time": w["duration_minutes"] * 60,  # Totale bewegingstijd in seconden
        "indoor": False  # Geeft aan dat het een outdoor workout is
    }


# ==========================
# PUSH TO INTERVALS.ICU
# ==========================

def push_workouts_to_intervals():
    url = f"{BASE_URL}/api/v1/athlete/{ATHLETE_ID}/events/bulk"  # Bulk endpoint voor workouts

    params = {
        "upsert": False,  # Geen automatische vervanging op basis van datum
        "upsertOnUid": UPSERT_ON_UID,  # Vervangen op basis van uid? (False)
        "updatePlanApplied": UPDATE_PLAN_APPLIED  # Updates doorvoeren in trainingsplan
    }

    # Bouw alle workouts om naar Intervals events
    events = [build_event_from_workout(w) for w in WORKOUTS]

    # Verstuur POST request naar Intervals API
    response = requests.post(
        url,
        json=events,  # JSON payload met alle workouts
        params=params,  # Query parameters voor API gedrag
        headers=get_headers(),  # HTTP headers (auth + type)
        auth=get_auth(),  # BasicAuth indien API key mode
        timeout=30  # Timeout om vastlopen te vermijden
    )

    print("Status:", response.status_code)  # Print HTTP statuscode

    try:
        print(response.json())  # Print JSON response indien mogelijk
    except:
        print(response.text)  # Zoniet, fallback naar normale tekst


# ==========================
# MAIN
# ==========================

if __name__ == "__main__":  # Voert dit blok uit wanneer script direct gestart wordt
    push_workouts_to_intervals()  # Start upload van workouts naar Intervals.icu
