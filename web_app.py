import importlib.util
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
import requests
from requests.auth import HTTPBasicAuth

from athletes import ATHLETES
from push_to_intervals import WORKOUTS, push_workouts_to_intervals
from datetime import datetime, timedelta

load_dotenv()

WORKOUTS_DIR = Path("Workouts")
ARCHIVE_DIR = WORKOUTS_DIR / "WorkoutsArchive"
WORKOUTS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

INTERVALS_API_KEY = os.getenv("INTERVALS_API_KEY")


def save_athletes():
    """Schrijf de ATHLETES dict weg naar athletes.py op alfabetische volgorde."""
    target = Path("athletes.py")
    lines = ["ATHLETES = {\n"]
    for n, i in sorted(ATHLETES.items(), key=lambda x: x[0].lower()):
        lines.append(f'    "{n}": "{i}",\n')
    lines.append("}\n")
    target.write_text("".join(lines), encoding="utf-8")


def resolve_workout_path(raw_path: str) -> Path:
    """
    Zorgt ervoor dat een gebruiker alleen files binnen de Workouts map kan aanspreken.
    """
    candidate = Path(raw_path).expanduser()
    resolved = candidate.resolve()
    root = WORKOUTS_DIR.resolve()

    if resolved.suffix != ".py":
        raise ValueError("Alleen .py files worden ondersteund.")

    if root not in resolved.parents and resolved != root:
        raise ValueError("Pad moet binnen de Workouts map liggen.")

    return resolved


def load_workouts_from_file(path: Path):
    """Laad WORKOUTS uit een willekeurige .py file."""
    if not path.exists():
        raise FileNotFoundError("Bestand bestaat niet (meer).")

    spec = importlib.util.spec_from_file_location(f"workouts_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "WORKOUTS"):
        raise ValueError("Bestand bevat geen WORKOUTS variabele.")

    return module.WORKOUTS


def summarize_workouts(workouts):
    """Enkele snelle metadata over de lijst."""
    dates = [w.get("date") for w in workouts if isinstance(w.get("date"), str)]
    start = min(dates) if dates else None
    end = max(dates) if dates else None
    return {"count": len(workouts), "start_date": start, "end_date": end}


def list_workout_files():
    """Geef alle beschikbare workoutfiles terug in de Workouts map (geen archief)."""
    return sorted(WORKOUTS_DIR.glob("*.py"))


def archive_workout_file(path: Path):
    """Verplaats een file naar het archief indien ze uit de hoofdmap komt."""
    archive_root = ARCHIVE_DIR.resolve()
    source_root = WORKOUTS_DIR.resolve()
    resolved = path.resolve()

    # Reeds in archief of buiten de hoofdmap? Dan laten we het zo.
    if archive_root in resolved.parents or resolved.parent != source_root:
        return None

    archive_root.mkdir(parents=True, exist_ok=True)

    target = archive_root / resolved.name
    if target.exists():
        # Voorkom overschrijven.
        stem, suffix = resolved.stem, resolved.suffix
        counter = 1
        while target.exists():
            target = archive_root / f"{stem}_archived_{counter}{suffix}"
            counter += 1

    shutil.move(str(resolved), target)
    return target


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/athletes")
def api_athletes():
    data = [{"name": name, "id": athlete_id} for name, athlete_id in ATHLETES.items()]
    return jsonify({"athletes": data})


@app.post("/api/athletes")
def api_add_athlete():
    payload = request.get_json(force=True, silent=True) or {}
    name = str(payload.get("name", "")).strip()
    athlete_id = str(payload.get("id", "")).strip()

    if not name or not athlete_id:
        return jsonify({"error": "Naam en Athlete ID zijn verplicht."}), 400

    # Update in-memory
    ATHLETES[name] = athlete_id

    # Persist naar athletes.py op een veilige manier
    try:
        save_athletes()
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Kon athletes.py niet wegschrijven: {exc}"}), 500

    return jsonify({"ok": True, "athletes": [{"name": n, "id": i} for n, i in ATHLETES.items()]})


@app.delete("/api/athletes")
def api_delete_athlete():
    payload = request.get_json(force=True, silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Naam is verplicht om te verwijderen."}), 400
    if name not in ATHLETES:
        return jsonify({"error": "Atleet niet gevonden."}), 404

    del ATHLETES[name]
    try:
        save_athletes()
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Kon athletes.py niet wegschrijven: {exc}"}), 500

    return jsonify({"ok": True, "athletes": [{"name": n, "id": i} for n, i in ATHLETES.items()]})


@app.route("/api/workouts")
def api_workouts():
    files = []
    for path in list_workout_files():
        meta = {"count": 0, "start_date": None, "end_date": None}
        error = None

        try:
            workouts = load_workouts_from_file(path)
            meta = summarize_workouts(workouts)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        files.append(
            {
                "name": path.name,
                "path": str(path),
                "location": "new",
                "count": meta.get("count"),
                "start_date": meta.get("start_date"),
                "end_date": meta.get("end_date"),
                "error": error,
            }
        )

    return jsonify({"files": files})


@app.post("/api/upload")
def api_upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "Geen file ontvangen."}), 400

    filename = file.filename or ""
    if not filename.lower().endswith(".py"):
        return jsonify({"error": "Alleen .py files zijn toegestaan."}), 400

    target = WORKOUTS_DIR / Path(filename).name
    if target.exists():
        return jsonify({"error": "Er bestaat al een file met deze naam in Workouts."}), 409

    target.parent.mkdir(parents=True, exist_ok=True)
    file.save(target)

    return jsonify({"ok": True, "path": str(target), "name": target.name})


@app.post("/api/upload-text")
def api_upload_text():
    payload = request.get_json(force=True, silent=True) or {}
    filename = str(payload.get("filename", "")).strip()
    content = payload.get("content", "")

    if not filename.lower().endswith(".py"):
        return jsonify({"error": "Alleen .py files zijn toegestaan."}), 400
    if not filename:
        return jsonify({"error": "Bestandsnaam is verplicht."}), 400
    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "Inhoud mag niet leeg zijn."}), 400

    target = WORKOUTS_DIR / Path(filename).name
    if target.exists():
        return jsonify({"error": "Er bestaat al een file met deze naam in Workouts."}), 409

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Kon file niet opslaan: {exc}"}), 500

    return jsonify({"ok": True, "path": str(target), "name": target.name})


@app.post("/api/push")
def api_push():
    payload = request.get_json(force=True, silent=True) or {}
    athlete_id = str(payload.get("athleteId", "")).strip()
    workout_path = payload.get("workoutPath")

    if not athlete_id:
        return jsonify({"error": "Athlete ID is verplicht."}), 400
    if not workout_path:
        return jsonify({"error": "Kies een workoutfile."}), 400

    try:
        resolved_path = resolve_workout_path(workout_path)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400

    if not resolved_path.exists():
        return jsonify({"error": "Bestand bestaat niet meer."}), 404

    try:
        workouts = load_workouts_from_file(resolved_path)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Kon workouts niet laden: {exc}"}), 400

    os.environ["ATHLETE_ID"] = athlete_id
    WORKOUTS.clear()
    WORKOUTS.extend(workouts)

    try:
        response = push_workouts_to_intervals()
        api_status = response.status_code if response is not None else None
        try:
            api_body = response.json() if response is not None else None
        except Exception:  # noqa: BLE001
            api_body = response.text if response is not None else None
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Upload mislukt: {exc}"}), 500

    archive_to = None
    archive_error = None
    try:
        archived = archive_workout_file(resolved_path)
        archive_to = str(archived) if archived else None
    except Exception as exc:  # noqa: BLE001
        archive_error = str(exc)

    return jsonify(
        {
            "ok": True,
            "apiStatus": api_status,
            "apiBody": api_body,
            "archivedTo": archive_to,
            "archiveError": archive_error,
        }
    )


@app.delete("/api/workouts")
def api_delete_workout():
    payload = request.get_json(force=True, silent=True) or {}
    workout_path = payload.get("workoutPath")
    if not workout_path:
        return jsonify({"error": "Kies een workoutfile om te verwijderen."}), 400

    try:
        resolved_path = resolve_workout_path(workout_path)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400

    if not resolved_path.exists():
        return jsonify({"error": "Bestand bestaat niet meer."}), 404

    try:
        resolved_path.unlink()
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Verwijderen mislukt: {exc}"}), 500

    return jsonify({"ok": True, "deleted": str(resolved_path), "name": resolved_path.name})


@app.get("/api/history")
def api_history():
    athlete_id = request.args.get("athleteId", "").strip()
    if not athlete_id:
        return jsonify({"error": "Athlete ID is verplicht."}), 400

    if not INTERVALS_API_KEY:
        return jsonify({"error": "INTERVALS_API_KEY ontbreekt in de omgeving."}), 500

    try:
        oldest = (datetime.utcnow() - timedelta(days=90)).date().isoformat()
        newest = datetime.utcnow().date().isoformat()
        events_newest = (datetime.utcnow() + timedelta(days=180)).date().isoformat()
        auth = HTTPBasicAuth("API_KEY", INTERVALS_API_KEY)

        activities_url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/activities"
        wellness_url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness"
        events_url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/events"

        activities_resp = requests.get(
            activities_url, params={"oldest": oldest, "newest": newest}, auth=auth, timeout=20
        )
        wellness_resp = requests.get(
            wellness_url, params={"start": oldest, "end": newest}, auth=auth, timeout=20
        )
        events_resp = requests.get(
            events_url, params={"oldest": oldest, "newest": events_newest}, auth=auth, timeout=20
        )

        activities_resp.raise_for_status()
        wellness_resp.raise_for_status()
        events_resp.raise_for_status()

        activities = activities_resp.json()
        wellness = wellness_resp.json()
        events = events_resp.json()
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response else 500
        body = exc.response.text if exc.response else str(exc)
        return jsonify({"error": f"API fout ({status})", "details": body}), status
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Ophalen mislukt: {exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "athleteId": athlete_id,
            "range": {"from": oldest, "to": newest},
            "activities": activities,
            "wellness": wellness,
            "events": events,
            "eventsRange": {"from": oldest, "to": events_newest},
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
