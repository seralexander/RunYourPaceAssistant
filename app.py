import os
import importlib.util
from dotenv import load_dotenv

# Importeer push-functionaliteit
from push_to_intervals import push_workouts_to_intervals, WORKOUTS


# ========================================
# Environment laden
# ========================================
load_dotenv()

WORKOUTS_DIR = "Workouts"


# ========================================
# Workoutfile dynamisch inladen
# ========================================
def load_workouts_from_py(filepath):
    spec = importlib.util.spec_from_file_location("workouts_module", filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "WORKOUTS"):
        print("❌ ERROR: De file bevat geen variabele WORKOUTS.")
        exit(1)

    return module.WORKOUTS


# ========================================
# Athlete ID handmatig ingeven
# ========================================
def choose_athlete():
    print("\n👤 Vul het Athlete ID in (zoals in Intervals.icu):\n")

    athlete_id = input("👉 Athlete ID: ").strip()

    if athlete_id == "":
        print("❌ Ongeldige invoer: Athlete ID mag niet leeg zijn.")
        exit(1)

    # Zet ATHLETE_ID environment variable
    os.environ["ATHLETE_ID"] = athlete_id

    print(f"\n➡️ Gekozen Athlete ID: {athlete_id}")

    return athlete_id


# ========================================
# Workoutfile kiezen
# ========================================
def choose_workout_file():
    print("\n📁 Beschikbare workout .py files:\n")

    files = [f for f in os.listdir(WORKOUTS_DIR) if f.endswith(".py")]

    if not files:
        print("❌ Geen .py workoutfiles gevonden in Workouts/")
        exit(1)

    for idx, filename in enumerate(files, start=1):
        print(f"{idx}. {filename}")

    choice = int(input("\n👉 Kies het nummer van de file: "))

    if choice < 1 or choice > len(files):
        print("❌ Ongeldige keuze.")
        exit(1)

    selected = files[choice - 1]
    full_path = os.path.join(WORKOUTS_DIR, selected)

    print(f"\n📄 Gekozen bestand: {selected}")

    return load_workouts_from_py(full_path)


# ========================================
# MAIN
# ========================================
def main():
    print("============================================")
    print("   🏋️  Intervals.icu Workout Uploader CLI")
    print("============================================\n")

    # 1. Straight athlete ID input
    athlete_id = choose_athlete()

    # 2. Workoutfile kiezen
    workouts = choose_workout_file()

    # 3. Inladen in WORKOUTS lijst (die uit push_to_intervals komt)
    WORKOUTS.clear()
    WORKOUTS.extend(workouts)

    # 4. Pushen naar Intervals.icu
    print(f"\n🚀 Workouts worden geüpload voor Athlete ID: {athlete_id}...\n")
    push_workouts_to_intervals()

    print("\n✅ Upload klaar!\n")


if __name__ == "__main__":
    main()
