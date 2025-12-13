import asyncio
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
import json

# Laad .env vroeg zodat keys beschikbaar zijn voor agent-initialisatie.
def _load_env_files():
    """Laad .env vanuit projectroot of naast dit bestand, zonder find_dotenv (kan falen in sommige shells)."""
    candidates = [
        Path(__file__).resolve().parent / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(dotenv_path=candidate, override=False)


_load_env_files()
# Zorg dat OPENAI_API_KEY zeker in de omgeving staat.
if os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

agent_setup_error = None
run_workflow = None
WorkflowInput = None
intake_setup_error = None
run_intake_workflow = None
IntakeWorkflowInput = None

try:
    from agents import (
        FileSearchTool,
        WebSearchTool,
        Agent,
        ModelSettings,
        TResponseInputItem,
        Runner,
        RunConfig,
        trace,
    )
    from openai.types.shared.reasoning import Reasoning
    from pydantic import BaseModel

    # Tool definitions
    file_search = FileSearchTool(vector_store_ids=["vs_69387711759c8191be0bfca2bec36f74"])
    web_search_preview = WebSearchTool(search_context_size="medium", user_location={"type": "approximate"})
    schemamaker = Agent(
        name="SchemaMaker",
        instructions="""Je bent RunYourPaceAssistant, een coachingsassistent voor hardlopers.

Belangrijke algemene richtlijnen

Je gebruikt inhoud uit TCONSPE-course.pdf als primaire bron voor trainingsprincipes, uitleg en onderbouwing.

Als je iets toevoegt dat niet rechtstreeks uit de cursus komt (bijvoorbeeld concrete minutenschema’s, afstanden, praktische vertaalslagen), vermeld je expliciet dat dit een eigen praktische invulling is bovenop de cursus.

Je schrijft normaal in het Nederlands, tenzij de gebruiker iets anders vraagt.

Trainingsinhoud

Je past principes toe uit de cursus (FITT, geleidelijke opbouw, periodisering, enz.) en verwijst er waar relevant naar.

Wanneer de gebruiker trainingsschema’s vraagt met RPE, gebruik je altijd onderstaande schaal:

RPE	Beschrijving
1	Zeer lichte inspanning. Nauwelijks merkbaar.
2	Lichte inspanning. Je voelt dat je beweegt, maar het kost weinig moeite.
3	Matig lichte inspanning. Je merkt inspanning, maar het is goed vol te houden.
4	Matige inspanning. Je ademhaling versnelt licht, je moet je beginnen concentreren.
5	Iets zwaarder. Duidelijke inspanning, maar controle blijft behouden.
6	Zware inspanning. Praten wordt moeilijker, focus is nodig.
7	Zeer zware inspanning. Ademhaling en hartslag sterk verhoogd.
8	Erg zware inspanning. Nauwelijks vol te houden. Beperkte duur mogelijk.
9	Bijna maximaal. Extreem zwaar. Slechts enkele seconden vol te houden.
10	Maximale inspanning. Totale uitputting. Langer doorgaan is onmogelijk.

Wanneer de gebruiker trainingsschema’s vraagt met hartslagzones, gebruik je altijd deze zones:

Zone	Naam	% van HFmax	Beschrijving
1	Herstelzone	50–60%	Zeer lichte inspanning. Bevordert herstel, minimale belasting.
2	Vetverbrandingszone	60–70%	Lichte tot matige inspanning. Basisuithouding en vetverbranding.
3	Aerobe zone	70–80%	Matig zware inspanning. Verhoogt aerobe capaciteit en efficiëntie.
4	Anaerobe zone	80–90%	Zware inspanning. Trainen rond de anaerobe drempel. Verbetert snelheid en kracht.
5	Maximale zone	90–100%	Maximale inspanning. Kort vol te houden. Vergroot maximale prestatiecapaciteit.
Intervals.icu & workout-bestanden

De gebruiker gebruikt Intervals.icu als trainingsapplicatie.

Wanneer je een workout.json-bestand moet maken:

JSON-workouts (heel belangrijk)

Wanneer de gebruiker vraagt om een JSON-workoutbestand:

Het bestand moet altijd een JSON-array zijn, dus:

Het JSON-document begint met [ en eindigt met ].

Elke entry in de array is één workout-object (dictionary) met minstens:

"date"

"name"

"duration_minutes"

"description"

Voorbeeld van een enkele training in JSON-arrayvorm:

[
  {
    "date": "2025-12-15",
    "name": "Duurloop Z2 35m",
    "duration_minutes": 35,
    "description": "Main Set\n- 35m Z2 HR"
  }
]
Elke workout in WORKOUTS moet:

Een date hebben (string, formaat YYYY-MM-DD).

Minstens een name, duration_minutes en description hebben.

In de description:

Moet elke regel die een blok training beschrijft beginnen met een - en daarna altijd zone én HR vermelden.

Voorbeeld: - 10m Z1 HR

Je zit altijd in 1 zone tegelijk: dus geen Z1-Z2, maar ofwel Z1 of Z2.

Gebruik s voor seconden, m voor minuten en h voor uren.

Voor intervaltrainingen volg je het voorbeeldformaat:

{
  "date": "2025-12-18",
  "name": "Interval 4x2m Z3",
  "duration_minutes": 50,
  "description": "Warmup\n- 10m Z1 HR\n\nMain Set\n4x\n- 2m Z3 HR\n- 2m Z2 HR\n\nCooldown\n- 10m Z1 HR"
}

Controleer de structuur van workout.json tegen de Intervals.icu API-documentatie vóór je de output geeft (voor zover mogelijk binnen je tools).


Je benoemt inconsistenties, ontbrekende velden of mogelijke problemen duidelijk.

Kort samengevat: je bent een hardloop-coachingsassistent die trainingen ontwerpt volgens de richtlijnen uit TCONSPE-course.pdf, schema’s vertaalt naar Intervals.icu-formaat (JSON), altijd duidelijke zones + HR in descriptions zet, en bij JSON-bestanden altijd een array gebruikt als toplaag.

!!! Als de gebruiker zegt 'push naar intervals.icu', dan antwoord je met een workout file in JSON formaat!!!""",
        model="gpt-5.1",
        tools=[file_search, web_search_preview],
        model_settings=ModelSettings(
            store=True,
            reasoning=Reasoning(
                effort="high",
                summary="auto",
            ),
        ),
    )

    class WorkflowInput(BaseModel):
        input_as_text: str

    async def run_workflow(workflow_input: WorkflowInput) -> str:
        """Draai de SchemaMaker agent met een enkele user prompt."""
        with trace("RunYourPaceAgent"):
            workflow = workflow_input.model_dump()
            conversation_history: list[TResponseInputItem] = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": workflow["input_as_text"],
                        }
                    ],
                }
            ]
            schemamaker_result_temp = await Runner.run(
                schemamaker,
                input=[*conversation_history],
                run_config=RunConfig(
                    trace_metadata={
                        "__trace_source__": "agent-builder",
                        "workflow_id": "wf_6936a4833bf481908ac80f10bcfa4bfc02a728dfdf564a27",
                    }
                ),
            )

            return schemamaker_result_temp.final_output_as(str)
except Exception as exc:  # noqa: BLE001
    agent_setup_error = str(exc)

try:
    # Intake agent setup
    file_search_intake = FileSearchTool(vector_store_ids=["vs_69387711759c8191be0bfca2bec36f74"])
    web_search_preview_intake = WebSearchTool(search_context_size="medium", user_location={"type": "approximate"})
    intake = Agent(
        name="Intake",
        instructions="""Je bent IntakeAgent, een professionele intake- en coachingsassistent voor het RunYourPace programma.

Jouw primaire taak:
- Een gestructureerd intakegesprek voeren met een atleet
- Alle noodzakelijke informatie verzamelen om een persoonlijk trainingsschema te kunnen opstellen
- Onvolledige, vage of tegenstrijdige antwoorden actief verduidelijken
- Pas wanneer de intake volledig en coherent is: een gestructureerde intake-samenvatting doorgeven aan de SchemaMaker agent

Je maakt zelf GEEN trainingsschema.
Je doet GEEN aannames zonder bevestiging van de atleet.
Je werkt coachend, helder en professioneel.

--------------------------------
CONVERSATIEAANPAK
--------------------------------
- Stel telkens één duidelijke vraag tegelijk
- Gebruik korte toelichting waarom een vraag relevant is indien nodig
- Vat regelmatig samen om te controleren of je de atleet correct begrijpt
- Indien de atleet iets niet weet (bv. hartslagzones): noteer dit expliciet als "onbekend"
- Respecteer medische voorzichtigheid: bij twijfel altijd noteren, nooit interpreteren

--------------------------------
INFORMATIE DIE JE MOET VERZAMELEN
--------------------------------

1. BASISGEGEVENS
- Voornaam
- Leeftijd of geboortejaar
- Geslacht (optioneel, zoals aangegeven door atleet)
- Lengte
- Gewicht
- E-mailadres
- Telefoonnummer

2. GEZONDHEID & MEDISCH
- Medische aandoeningen waarmee rekening moet worden gehouden
- Medicatie die invloed kan hebben op training
- Huidige blessures of pijnklachten
- Blessures in de afgelopen 2 jaar
- Eventuele medische beperkingen of aandachtspunten

3. SPORTACHTERGROND
- Welke sporten beoefent de atleet momenteel?
- Hoe vaak sport de atleet per week (totaal)?
- Hoe vaak loopt de atleet per week?
- Beschrijving van huidige uithouding
- Recente wedstrijdresultaten (indien van toepassing)

4. TRAININGSMETING & DATA
- Beschikt de atleet over een sporthorloge met hartslagmeting?
- Kent de atleet zijn/haar hartslagzones?
- Werd er ooit een lactaattest gedaan?
- Indien gekend:
  - LT1
  - LT2
  - Beschrijving van 5 hartslagzones
- Voorkeur trainingssturing:
  - Hartslagzones
  - RPE / gevoel
  - Combinatie

5. PRAKTISCHE HAALBAARHEID
- Hoeveel dagen per week wil de atleet realistisch lopen?
- Welke dagen zijn meestal beschikbaar voor training?
- Eventuele vaste rustdagen
- Beperkingen door werk, gezin of andere belasting

6. DOELEN
- Wat is het belangrijkste doel van dit trainingsprogramma?
- Wordt er getraind voor een specifiek event?
  - Naam event
  - Datum
  - Afstand
  - Doeltijd (indien relevant)

7. MOTIVATIE & COACHINGSTIJL
- Wat motiveert de atleet het meest om dit programma te volgen?
- Wat verwacht de atleet van een coach?
  - Actieve motivatie
  - Klankbord
  - Structuur
  - Flexibiliteit
- Hoe zelfstandig voelt de atleet zich in training?

8. PLATFORM & OPVOLGING
- Bevestiging dat de atleet zal werken met Intervals.icu
- Bereidheid om data te delen voor coaching
- Eventuele vragen of drempels rond het platform

--------------------------------
AFRONDING
--------------------------------
- Controleer expliciet of alle bovenstaande onderdelen zijn ingevuld
- Geef een korte samenvatting van wat je hebt begrepen
- Vraag bevestiging van de atleet dat dit correct is
- Pas na bevestiging: ga door naar overdracht

--------------------------------
EINDE
--------------------------------
Wanneer de intake volledig is, geef je een gestructureerd verslag terug in text aan de gebruiker.
Met de vraag om dit na te lezen. 

- athlete_profile
- health_constraints
- training_background
- measurement_preferences
- availability
- goals
- motivation_profile
- platform_constraints
- open_questions_or_risks
""",
        model="gpt-5.1",
        tools=[file_search_intake, web_search_preview_intake],
        model_settings=ModelSettings(
            store=True,
            reasoning=Reasoning(effort="high", summary="auto"),
        ),
    )

    class IntakeWorkflowInput(BaseModel):
        input_as_text: str

    async def run_intake_workflow(workflow_input: IntakeWorkflowInput) -> str:
        """Draai de Intake agent met een enkele user prompt."""
        with trace("RunYourPaceIntakeAgent"):
            workflow = workflow_input.model_dump()
            conversation_history: list[TResponseInputItem] = [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": workflow["input_as_text"]}],
                }
            ]
            intake_result_temp = await Runner.run(
                intake,
                input=[*conversation_history],
                run_config=RunConfig(
                    trace_metadata={
                        "__trace_source__": "agent-builder",
                        "workflow_id": "wf_693bc699c7788190a6fb5bf976e6c6e90864f6e8b356c496",
                    }
                ),
            )
            return intake_result_temp.final_output_as(str)
except Exception as exc:  # noqa: BLE001
    intake_setup_error = str(exc)

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

    if resolved.suffix != ".json":
        raise ValueError("Alleen .json files worden ondersteund.")

    if root not in resolved.parents and resolved != root:
        raise ValueError("Pad moet binnen de Workouts map liggen.")

    return resolved


def load_workouts_from_file(path: Path):
    """Laad WORKOUTS uit een .json file."""
    if not path.exists():
        raise FileNotFoundError("Bestand bestaat niet (meer).")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Kon JSON niet parsen: {exc}") from exc

    # Ondersteun zowel een lijst als een object met key WORKOUTS voor compatibiliteit
    if isinstance(data, dict) and "WORKOUTS" in data:
        workouts = data["WORKOUTS"]
    else:
        workouts = data

    if not isinstance(workouts, list):
        raise ValueError("Bestand moet een lijst van workouts bevatten.")

    return workouts


def summarize_workouts(workouts):
    """Enkele snelle metadata over de lijst."""
    dates = [w.get("date") for w in workouts if isinstance(w.get("date"), str)]
    start = min(dates) if dates else None
    end = max(dates) if dates else None
    return {"count": len(workouts), "start_date": start, "end_date": end}


def list_workout_files():
    """Geef alle beschikbare workoutfiles terug in de Workouts map (geen archief)."""
    return sorted(WORKOUTS_DIR.glob("*.json"))


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


@app.post("/api/agent-test")
def api_agent_test():
    payload = request.get_json(force=True, silent=True) or {}
    message = str(payload.get("message", "")).strip()

    if not message:
        return jsonify({"error": "Bericht is verplicht."}), 400
    if not os.getenv("OPENAI_API_KEY"):
        return (
            jsonify(
                {
                    "error": "Agent niet beschikbaar: OPENAI_API_KEY ontbreekt.",
                    "hint": "Zet OPENAI_API_KEY in je .env of als environment variabele en start de app opnieuw.",
                }
            ),
            500,
        )
    if agent_setup_error or run_workflow is None or WorkflowInput is None:
        return jsonify({"error": f"Agent niet beschikbaar: {agent_setup_error or 'initialisatie mislukt.'}"}), 500

    try:
        reply = asyncio.run(run_workflow(WorkflowInput(input_as_text=message)))
    except Exception as exc:  # noqa: BLE001
        # Geef iets meer debug-info terug voor key-fouten.
        return (
            jsonify(
                {
                    "error": f"Agent call mislukt: {exc}",
                    "agent_setup_error": agent_setup_error,
                    "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
                }
            ),
            500,
        )

    return jsonify({"ok": True, "reply": reply})


@app.post("/api/intake")
def api_intake():
    payload = request.get_json(force=True, silent=True) or {}
    message = str(payload.get("message", "")).strip()
    transcript = payload.get("transcript") or []

    if not message:
        return jsonify({"error": "Bericht is verplicht."}), 400
    if not os.getenv("OPENAI_API_KEY"):
        return (
            jsonify(
                {
                    "error": "Agent niet beschikbaar: OPENAI_API_KEY ontbreekt.",
                    "hint": "Zet OPENAI_API_KEY in je .env of als environment variabele en start de app opnieuw.",
                }
            ),
            500,
        )
    if intake_setup_error or run_intake_workflow is None or IntakeWorkflowInput is None:
        return jsonify({"error": f"Intake agent niet beschikbaar: {intake_setup_error or 'initialisatie mislukt.'}"}), 500

    # Combineer transcript in één prompt zodat de agent context heeft.
    transcript_lines = []
    for item in transcript:
        role = item.get("role", "user")
        text = item.get("text", "")
        transcript_lines.append(f"{role}: {text}")
    prefix = ""
    if transcript_lines:
        prefix = "Eerder intakegesprek:\n" + "\n".join(transcript_lines) + "\n\nVervolg:\n"

    try:
        reply = asyncio.run(run_intake_workflow(IntakeWorkflowInput(input_as_text=f"{prefix}{message}")))
    except Exception as exc:  # noqa: BLE001
        return (
            jsonify(
                {
                    "error": f"Intake call mislukt: {exc}",
                    "intake_setup_error": intake_setup_error,
                    "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
                }
            ),
            500,
        )

    return jsonify({"ok": True, "reply": reply})


@app.post("/api/schema-chat")
def api_schema_chat():
    """Vrije chat met de SchemaMaker agent (zonder intake-flow)."""
    payload = request.get_json(force=True, silent=True) or {}
    message = str(payload.get("message", "")).strip()
    transcript = payload.get("transcript") or []

    if not message:
        return jsonify({"error": "Bericht is verplicht."}), 400
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "Agent niet beschikbaar: OPENAI_API_KEY ontbreekt."}), 500
    if agent_setup_error or run_workflow is None or WorkflowInput is None:
        return jsonify({"error": f"Schema agent niet beschikbaar: {agent_setup_error or 'initialisatie mislukt.'}"}), 500

    transcript_lines = []
    for item in transcript:
        role = item.get("role", "user")
        text = item.get("text", "")
        transcript_lines.append(f"{role}: {text}")
    prefix = ""
    if transcript_lines:
        prefix = "Eerder gesprek over schema:\n" + "\n".join(transcript_lines) + "\n\nVervolg:\n"

    try:
        reply = asyncio.run(run_workflow(WorkflowInput(input_as_text=f"{prefix}{message}")))
    except Exception as exc:  # noqa: BLE001
        return (
            jsonify(
                {
                    "error": f"Schema-chat mislukt: {exc}",
                    "agent_setup_error": agent_setup_error,
                    "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
                }
            ),
            500,
        )

    return jsonify({"ok": True, "reply": reply})


@app.post("/api/schedule-adjust")
def api_schedule_adjust():
    """
    Laat de SchemaMaker agent een aangepast schema teruggeven op basis van feedback + huidige schema.
    """
    payload = request.get_json(force=True, silent=True) or {}
    feedback = str(payload.get("feedback", "")).strip()
    transcript = payload.get("transcript") or []
    current_schema = str(payload.get("currentSchema", "")).strip()

    if not feedback:
        return jsonify({"error": "Feedback is verplicht."}), 400
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "Agent niet beschikbaar: OPENAI_API_KEY ontbreekt."}), 500
    if agent_setup_error or run_workflow is None or WorkflowInput is None:
        return jsonify({"error": f"Schema agent niet beschikbaar: {agent_setup_error or 'initialisatie mislukt.'}"}), 500

    transcript_lines = []
    for item in transcript:
        role = item.get("role", "user")
        text = item.get("text", "")
        transcript_lines.append(f"{role}: {text}")
    convo = "\n".join(transcript_lines) if transcript_lines else ""

    prompt_parts = [
        "Je bent SchemaMaker. Pas het trainingsschema aan op basis van de feedback. Geef het nieuwe schema in duidelijke, gestructureerde opsomming.",
        "Huidig schema:",
        current_schema or "(geen schema tekst beschikbaar)",
        "Feedback van gebruiker:",
        feedback,
    ]
    if convo:
        prompt_parts.append("Eerder gesprek:")
        prompt_parts.append(convo)

    prompt = "\n\n".join(prompt_parts)

    try:
        reply = asyncio.run(run_workflow(WorkflowInput(input_as_text=prompt)))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Schema-aanpassing mislukt: {exc}"}), 500

    return jsonify({"ok": True, "reply": reply})


@app.post("/api/schedule-table")
def api_schedule_table():
    """Vraag de SchemaMaker agent om een tabelvormig schema te maken op basis van het intakeverslag."""
    payload = request.get_json(force=True, silent=True) or {}
    report = str(payload.get("report", "")).strip()
    if not report:
        return jsonify({"error": "Intake verslag ontbreekt."}), 400
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "OPENAI_API_KEY ontbreekt."}), 500
    if agent_setup_error or run_workflow is None or WorkflowInput is None:
        return jsonify({"error": f"Schema agent niet beschikbaar: {agent_setup_error or 'initialisatie mislukt.'}"}), 500

    prompt = (
        "Gebruik dit intake-verslag om een trainingsschema terug te geven in een duidelijke, gestructureerde opsomming "
        "(geen ASCII tabel). Geef per sessie: datum, sessie/naam, duur, zone/RPE en een korte beschrijving met blokken. "
        "Houd het compact en goed leesbaar. Intake verslag:\n\n"
        f"{report}"
    )
    try:
        reply = asyncio.run(run_workflow(WorkflowInput(input_as_text=prompt)))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Schema-call mislukt: {exc}"}), 500

    return jsonify({"ok": True, "reply": reply})


@app.post("/api/schedule-json-push")
def api_schedule_json_push():
    """Laat de SchemaMaker agent het schema omzetten naar JSON en push het naar Intervals.icu."""
    payload = request.get_json(force=True, silent=True) or {}
    schema_text = str(payload.get("schemaText", "")).strip()
    athlete_id = str(payload.get("athleteId", "")).strip()

    if not schema_text:
        return jsonify({"error": "Schema-tekst ontbreekt."}), 400
    if not athlete_id:
        return jsonify({"error": "Athlete ID ontbreekt."}), 400
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "OPENAI_API_KEY ontbreekt."}), 500
    if agent_setup_error or run_workflow is None or WorkflowInput is None:
        return jsonify({"error": f"Schema agent niet beschikbaar: {agent_setup_error or 'initialisatie mislukt.'}"}), 500

    json_prompt = (
        "Zet onderstaand schema om naar een JSON array met workouts volgens de Intervals.icu richtlijn "
        "(velden: date, name, duration_minutes, description). "
        "Antwoord met alleen de JSON, geen uitleg. Schema:\n\n"
        f"{schema_text}"
    )

    try:
        json_reply = asyncio.run(run_workflow(WorkflowInput(input_as_text=json_prompt)))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"JSON-conversie mislukt: {exc}"}), 500

    try:
        parsed = json.loads(json_reply)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Kon JSON niet parsen: {exc}", "raw": json_reply}), 400

    if not isinstance(parsed, list):
        return jsonify({"error": "JSON moet een array van workouts zijn.", "raw": json_reply}), 400

    os.environ["ATHLETE_ID"] = athlete_id
    WORKOUTS.clear()
    WORKOUTS.extend(parsed)

    try:
        response = push_workouts_to_intervals()
        api_status = response.status_code if response is not None else None
        try:
            api_body = response.json() if response is not None else None
        except Exception:  # noqa: BLE001
            api_body = response.text if response is not None else None
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Upload mislukt: {exc}", "jsonReply": json_reply}), 500

    return jsonify({"ok": True, "json": parsed, "jsonReply": json_reply, "apiStatus": api_status, "apiBody": api_body})


@app.post("/api/schema-json-chat-push")
def api_schema_json_chat_push():
    """
    Zet de vrije schema-chat om naar JSON en push naar Intervals.icu.
    Verwacht: athleteId, transcript (lijst met role/text).
    """
    payload = request.get_json(force=True, silent=True) or {}
    athlete_id = str(payload.get("athleteId", "")).strip()
    transcript = payload.get("transcript") or []

    if not athlete_id:
        return jsonify({"error": "Athlete ID ontbreekt."}), 400
    if not transcript:
        return jsonify({"error": "Geen gesprek om te converteren."}), 400
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "OPENAI_API_KEY ontbreekt."}), 500
    if agent_setup_error or run_workflow is None or WorkflowInput is None:
        return jsonify({"error": f"Schema agent niet beschikbaar: {agent_setup_error or 'initialisatie mislukt.'}"}), 500

    transcript_lines = []
    for item in transcript:
        role = item.get("role", "user")
        text = item.get("text", "")
        transcript_lines.append(f"{role}: {text}")

    convo_text = "\n".join(transcript_lines)
    json_prompt = (
        "Zet dit gesprek direct om naar een JSON array met workouts volgens de Intervals.icu richtlijn "
        "(velden: date, name, duration_minutes, description). "
        "Antwoord ALLEEN met de JSON-array (beginnend met [ en eindigend met ]), geen uitleg of tekst eromheen. "
        "Gesprek:\n\n"
        f"{convo_text}"
    )

    try:
        json_reply = asyncio.run(run_workflow(WorkflowInput(input_as_text=json_prompt)))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Schema-chat mislukt: {exc}"}), 500

    try:
        parsed = json.loads(json_reply)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Kon JSON niet parsen: {exc}", "raw": json_reply}), 400

    if not isinstance(parsed, list):
        return jsonify({"error": "JSON moet een array van workouts zijn.", "raw": json_reply}), 400

    os.environ["ATHLETE_ID"] = athlete_id
    WORKOUTS.clear()
    WORKOUTS.extend(parsed)

    try:
        response = push_workouts_to_intervals()
        api_status = response.status_code if response is not None else None
        try:
            api_body = response.json() if response is not None else None
        except Exception:  # noqa: BLE001
            api_body = response.text if response is not None else None
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Upload mislukt: {exc}", "jsonReply": json_reply}), 500

    return jsonify({"ok": True, "json": parsed, "jsonReply": json_reply, "apiStatus": api_status, "apiBody": api_body})


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
    if not filename.lower().endswith(".json"):
        return jsonify({"error": "Alleen .json files zijn toegestaan."}), 400

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

    if not filename.lower().endswith(".json"):
        return jsonify({"error": "Alleen .json files zijn toegestaan."}), 400
    if not filename:
        return jsonify({"error": "Bestandsnaam is verplicht."}), 400
    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "Inhoud mag niet leeg zijn."}), 400

    target = WORKOUTS_DIR / Path(filename).name
    if target.exists():
        return jsonify({"error": "Er bestaat al een file met deze naam in Workouts."}), 409

    try:
        parsed = json.loads(content)
        # Validate basic structure before saving
        if isinstance(parsed, dict) and "WORKOUTS" in parsed:
            parsed_workouts = parsed["WORKOUTS"]
        else:
            parsed_workouts = parsed
        if not isinstance(parsed_workouts, list):
            return jsonify({"error": "JSON moet een lijst met workouts bevatten (of een object met key WORKOUTS)."}), 400

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
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


@app.get("/api/agent-status")
def api_agent_status():
    """Snelle healthcheck voor de agentconfig zonder secrets te lekken."""
    return jsonify(
        {
            "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
            "agent_setup_error": agent_setup_error,
            "agent_ready": bool(run_workflow and WorkflowInput and not agent_setup_error),
        }
    )


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
