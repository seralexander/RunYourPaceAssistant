import os
import json
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

# Import atleten vanuit je rootfolder
from athletes import ATHLETES

load_dotenv()

API_KEY = os.getenv("INTERVALS_API_KEY")
BASE_URL = "https://intervals.icu/api/v1"


def get_last_3_months_activities(athlete_id: str):
    """
    Haalt alle activiteiten op van de afgelopen 3 maanden voor de gegeven athlete_id.
    Returnt een lijst van activity dicts.
    """
    today = date.today()
    oldest = (today - timedelta(days=90)).isoformat()
    newest = today.isoformat()

    url = f"{BASE_URL}/athlete/{athlete_id}/activities"
    params = {
        "oldest": oldest,
        "newest": newest
    }

    response = requests.get(url, params=params, auth=("API_KEY", API_KEY))

    if not response.ok:
        raise Exception(f"Error {response.status_code}: {response.text}")

    return response.json()


def save_activities_to_json(activities, athlete_name, filename=None):
    """
    Slaat een JSON-bestand op in de map 'GetActivities'.
    Bestandsnaam bevat automatisch de atleetnaam + datum.
    """

    output_dir = "GetActivities"
    os.makedirs(output_dir, exist_ok=True)

    if filename is None:
        today_str = date.today().strftime("%Y%m%d")
        # vervang spaties in naam zodat het een geldige bestandsnaam wordt
        safe_name = athlete_name.replace(" ", "_")
        filename = f"{safe_name}_activities_{today_str}.json"

    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(activities, f, ensure_ascii=False, indent=4)

    print(f"JSON opgeslagen als: {filepath}")


def select_athlete():
    """
    Laat de gebruiker een atleet kiezen via terminal input.
    """
    print("Beschikbare atleten:\n")
    for name in ATHLETES.keys():
        print(f"- {name}")

    choice = input("\nTyp exact de naam van de atleet: ").strip()

    if choice not in ATHLETES:
        raise ValueError(f"Atleet '{choice}' bestaat niet in ATHLETES in athletes.py")

    return choice, ATHLETES[choice]


if __name__ == "__main__":
    # 1. Selecteer atleet
    athlete_name, athlete_id = select_athlete()

    print(f"\nActiviteiten ophalen voor: {athlete_name} (ID: {athlete_id})...\n")

    # 2. Activiteiten ophalen
    activities = get_last_3_months_activities(athlete_id)

    # 3. Wegschrijven naar JSON file
    save_activities_to_json(activities, athlete_name)
