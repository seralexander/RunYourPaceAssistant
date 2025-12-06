import os
import importlib.util
import shutil
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

    workouts = load_workouts_from_py(full_path)

    return workouts, full_path


# ========================================
# Workoutfile archiveren
# ========================================
def archive_workout_file(filepath):
    archive_dir = os.path.join(WORKOUTS_DIR, "WorkoutsArchive")

    # Map aanmaken indien nodig
    os.makedirs(archive_dir, exist_ok=True)

    filename = os.path.basename(filepath)
    new_path = os.path.join(archive_dir, filename)

    try:
        shutil.move(filepath, new_path)
        print(f"📦 Workoutfile verplaatst naar archive: {new_path}")
    except Exception as e:
        print(f"❌ Kon file niet verplaatsen naar archive: {e}")


# ========================================
# MAIN
# ========================================
def main():
    print("============================================")
    print("   🏋️  Intervals.icu Workout Uploader CLI")
    print("============================================\n")

    # 1. Athlete ID ingeven
    athlete_id = choose_athlete()

    # 2. Workoutfile kiezen
    workouts, filepath = choose_workout_file()

    # 3. Inladen in WORKOUTS lijst
    WORKOUTS.clear()
    WORKOUTS.extend(workouts)

    # 4. File archiveren
    archive_workout_file(filepath)

    # 5. Pushen naar Intervals.icu
    print(f"\n🚀 Workouts worden geüpload voor Athlete ID: {athlete_id}...\n")
    push_workouts_to_intervals()

    print("\n✅ Upload klaar!\n")


if __name__ == "__main__":
    main()
