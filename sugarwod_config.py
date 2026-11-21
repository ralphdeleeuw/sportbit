"""Vaste configuratie voor de SugarWOD-fetcher en de AI-coach (atletenprofiel, schema, URL's)."""
from __future__ import annotations

from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

SUGARWOD_BASE = "https://app.sugarwod.com"
LOGIN_URL = f"{SUGARWOD_BASE}/public/api/v1/login"
WORKOUTS_URL = f"{SUGARWOD_BASE}/workouts"
GIST_FILENAME = "sugarwod_wod.json"
AMS = ZoneInfo("Europe/Amsterdam")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

# ──────────────────────────────────────────────────────────────
# Athlete profile (used for AI coaching plans)
# ──────────────────────────────────────────────────────────────

BARBELL_LIFTS_FALLBACK = {
    "3 Position Clean (hang, below knee, floor)": {"1RM": 37.5, "3RM": 37},
    "3 Position Snatch (High Hang, Above the Knee, Floor)": {"1RM": 25, "3RM": 35},
    "Back Pause Squat": {"5RM": 43},
    "Back Rack Lunges": {"1RM": 50, "2RM": 50, "3RM": 50, "5RM": 50},
    "Back Squat": {"1RM": 67, "2RM": 60, "3RM": 62, "5RM": 56},
    "Bench Press": {"1RM": 67.5, "2RM": 55, "3RM": 60, "5RM": 50},
    "Bent Over Row": {"5RM": 30},
    "Box Squat": {"1RM": 90},
    "Clean": {"1RM": 50, "2RM": 53, "3RM": 40},
    "Clean & Jerk": {"1RM": 58, "2RM": 32.5, "3RM": 53},
    "Deadlift": {"1RM": 100, "2RM": 80, "3RM": 80, "5RM": 90},
    "Front Pause Squat": {"2RM": 37.5},
    "Front Rack Lunges": {"1RM": 35, "2RM": 35, "3RM": 35, "5RM": 35},
    "Front Squat": {"1RM": 65, "3RM": 35, "5RM": 57},
    "Front Squat + Jerk": {"5RM": 52.5},
    "Full Grip, No Foot Clean + Tall Jerks": {"5RM": 50},
    "Hang Clean": {"1RM": 55, "3RM": 40},
    "Hang Power Clean": {"1RM": 57.5, "3RM": 43, "5RM": 50},
    "Hang Power Snatch": {"1RM": 40, "2RM": 33, "3RM": 38},
    "Hang Squat Clean": {"3RM": 42.5, "5RM": 30},
    "Hang Squat Snatch": {"1RM": 35, "2RM": 35, "3RM": 32.5},
    "In The Hole Front Squat": {"1RM": 45},
    "Muscle Clean": {"5RM": 35},
    "Overhead Squat": {"1RM": 48, "2RM": 44},
    "Power Clean": {"1RM": 57, "2RM": 57, "3RM": 45},
    "Power Clean & Jerk": {"1RM": 61, "2RM": 61, "3RM": 58},
    "Power Snatch": {"1RM": 43, "2RM": 43, "3RM": 35, "5RM": 35},
    "Pressing Complex": {"1RM": 50},
    "Push Jerk": {"1RM": 61, "2RM": 61, "3RM": 50, "5RM": 40},
    "Push Press": {"1RM": 57.5, "2RM": 50, "5RM": 40},
    "Shoulder Press": {"1RM": 42.5, "2RM": 37.5, "3RM": 35, "5RM": 27},
    "Snatch": {"1RM": 38, "2RM": 34, "3RM": 35},
    "Snatch + Overhead Squat": {"2RM": 25},
    "Snatch Balance": {"1RM": 37.5, "2RM": 30, "3RM": 25},
    "Snatch Deadlift + High Hang Shrug": {"5RM": 37.5},
    "Snatch Grip Deadlift": {"3RM": 37.5},
    "Snatch Grip Push Press": {"5RM": 37.5},
    "Snatch Pull": {"2RM": 40},
    "Snatch Push Press + Overhead Squat": {"2RM": 40, "3RM": 27},
    "Split Jerk": {"1RM": 50, "2RM": 58},
    "Squat Clean": {"1RM": 53, "3RM": 40, "5RM": 35},
    "Squat Snatch": {"1RM": 45, "3RM": 32, "5RM": 30},
    "Sumo Deadlift": {"2RM": 50, "3RM": 50},
    "Sumo Deadlift High Pull": {"5RM": 43},
    "Thruster": {"1RM": 53, "2RM": 43, "3RM": 44, "5RM": 43},
    "Weighted Chin Up": {"1RM": 7.5, "3RM": 7.5},
    "Weighted Hip Thrust": {"5RM": 110},
}

ATHLETE_PROFILE = {
    "name": "Ralph de Leeuw",
    "weight_kg": 77,
    "experience": "intermediate-advanced (4+ jaar CrossFit)",
    "rx_preference": "mix van RX en Scaled — RX wanneer mogelijk",
    # Fallback — actuele blessures komen uit health_input.json ("injuries"), zie injuries.py
    "injuries": "geen",
    "gym": "CrossFit Hilversum",
    "doel": "Uiteindelijk alles RX kunnen. Leeftijd 47, voelt zich goed en traint serieus.",
    "skill_focus": [
        "hardlooptempo (sneller worden op 400m/800m/1mi)",
        "back squat & front squat (techniek + kracht)",
        "double unders (consistentie en hoog volume)",
        "handstand push-ups (strikt en kipping, richting RX)",
        "pull-ups (kipping en butterfly, richting RX)",
        "handstand walk (afstand opbouwen)",
    ],
}

# Weekly training schedule: weekday (0=Mon) → start time
# Mirrors the SCHEDULE in autosignup.py
TRAINING_SCHEDULE: dict[int, str] = {
    0: "20:00",  # Monday
    2: "08:00",  # Wednesday
    3: "20:00",  # Thursday
    6: "09:00",  # Sunday
}

# Dinner time — used to reason about pre/post-workout nutrition
DINNER_TIME = "18:00"

# Fixed breakfast — always the same high-protein meal, eaten around 07:00
BREAKFAST = {
    "time": "07:00",
    "description": (
        "Vast ontbijt (~838 kcal | ~56g eiwit | ~61g KH | ~36g vet): "
        "Alpro Mild & Creamy zonder suikers (200ml) met Holie's Granola Protein Crunch (75g) "
        "en Upfront Vegan Eiwit Shake chocolade (30g). "
        "Daarnaast 2 volkoren boterhammen met AH amandelpasta (~15g) en een beetje pure hagelslag (~10g)."
    ),
}

# Titels van hoofd-onderdelen van een WOD (metcon, kracht, …)
_MAIN_KEYWORDS = ("metcon", "weightlifting", "team metcon", "strength", "conditioning")
