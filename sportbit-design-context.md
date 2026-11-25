# SportBit — App Design Context

## Overview

**SportBit** is a personal fitness dashboard and automation system built for a single CrossFit athlete (Ralph de Leeuw, 47, CrossFit Hilversum, Netherlands). It centralizes data from multiple fitness platforms, automates class registrations, and delivers AI-powered coaching — all surfaced through a mobile-first progressive web app.

**Primary goals:**
- Auto-register for weekly CrossFit WOD classes
- Aggregate health & performance data from wearables and fitness apps
- Generate personalized AI coaching and running plans
- Provide a single-screen daily fitness overview

---

## Target User

| Attribute | Detail |
|-----------|--------|
| Name | Ralph de Leeuw |
| Age | 47 |
| Sport | CrossFit + recreational running |
| Box | CrossFit Hilversum, Netherlands |
| Weekly schedule | Mon 20:00 / Wed 08:00 / Thu 20:00 / Sat 09:00 / Sun 09:00 |
| Running goal | Defensie fitnesstest: 12 min ≥ 2200 m (eis), streef 2700 m; 5K ≈ 28:00 |
| Strength focus | Back squat, deadlift, Olympic lifts |
| Language | Dutch (nl) |
| Timezone | Europe/Amsterdam (CET/CEST) |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vanilla JS PWA — `index.html` + modules in `js/` (classic scripts, `main.js` laatst) |
| Charts | Chart.js v4 |
| Markdown rendering | marked.js |
| PWA | Service Worker + Web App Manifest |
| Backend/automation | Python 3.12, GitHub Actions (cron) |
| Data storage | GitHub Gist (JSON files, no database) |
| AI coaching | Anthropic Claude API |
| Notifications | Web Push (VAPID, via `notify.py`) |
| Calendar sync | Google Calendar API |

**Data sources integrated:**
- SugarWOD (CrossFit WODs, athlete notes, PRs)
- Strava (running & outdoor activities)
- Intervals.icu / Garmin Connect (wellness: HRV, sleep, training load)
- Withings (body composition: weight, fat %, muscle mass)
- Open-Meteo + WAQI (weather & air quality)

---

## Design System

### Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| Background | `#0d0d0d` | App background (near-black) |
| Surface | `#1a1a1a` | Cards, panels |
| Surface raised | `#222222` | Elevated elements |
| Accent primary | `#e8ff3c` | Neon yellow-green — CTAs, highlights, active states |
| Accent danger | `#ff4c2b` | Coral red — cancellations, warnings |
| Accent success | `#00c853` | Green — running, completed, healthy metrics |
| Accent info | `#4db8ff` | Blue — personal events, data labels |
| Accent alt | `#9a70ff` | Purple — recovery/wellness section |
| Text primary | `#f0f0f0` | Body text |
| Text muted | `#888888` | Secondary labels, timestamps |
| Border | `#333333` | Dividers, card borders |

### Typography

| Role | Font | Weight | Notes |
|------|------|--------|-------|
| Display / heading | Bebas Neue | 400 | Geometric all-caps — section titles, stats |
| Body | DM Sans | 300–500 | Clean sans — labels, descriptions, notes |
| Numbers / data | DM Sans | 500 | Tabular figures for metrics |

### Spacing & Layout

- Max-width container: **640px** (mobile-first)
- Base spacing unit: 8px
- Card padding: 16px
- Section gap: 24px
- Border radius: 10–14px (cards), 6px (badges/chips), 50px (pills)

### Animations

| Name | Duration | Easing | Usage |
|------|----------|--------|-------|
| fadeUp | 0.4s | ease | Cards entering viewport |
| fadeDown | 0.6s | ease | Header entrance |
| spin | 0.7s | linear | Loading spinner |
| skeleton-pulse | 1.4s | ease-in-out | Skeleton loader shimmer |

---

## Screen Architecture

Vijf tabs met een vaste bottom-navigatie. Bovenaan verschijnt een **sync-balk**
zodra er een workflow loopt (op elke tab zichtbaar), en een **offline-banner** als
de app op lokaal bewaarde data draait. Meldingen gaan via **toasts** onderaan
(met "Ongedaan maken" bij verwijderen); bevestigen via een bottom-sheet.

### 1. Vandaag
- Waarschuwingschip als een databron te oud is of een workflow mislukte
- **Dagadvies**: groen "Vol gas" / oranje "Rustig aan" / rood "Rust", op basis van
  HRV, rusthartslag, slaap, TSB, Garmin-gereedheid, blessures en belasting 7:28;
  uitklapbaar met de redenen
- Actieve blessures, thuistraining, herstelblok + AI-coach
- Pull-to-refresh

### 2. Schema
- Komende CrossFit-lessen, hardloopworkouts en eigen events
- Nog niet ingeschreven slots (vakantiedagen uitgesloten), maandquotum 13 lessen
- Geannuleerd + verleden activiteiten

### 3. Hardlopen
- Prestatievoorspeller: 5K-tijd + 12-minutenafstand (Riegel, snelste run per week),
  grafiek met lijnen voor 2200 m en 2700 m
- Hardloopplan, run-analyse en aanpassingsvoorstellen

### 4. CrossFit
- PR's, benchmarks, barbell-progressie (grafiek + tabel)

### 5. Acties
- Instellingen (Gist ID, token) + uitleg fine-grained token
- Databronnen-versheid (groen/rood per bron, link naar mislukte run)
- Trainingsbelasting (acuut:chronisch, alle sporten samen)
- Blessures, vakantiemodus
- Workflowknoppen met laatste-run-status, notificaties, ruwe data-tabellen

---

## Key UI Components

| Component | Description |
|-----------|-------------|
| **Event Card** | Rounded card with left-border status color, expandable WOD section, action buttons |
| **Capacity Badge** | Pill badge showing "current/max" participants, color-coded by fill level |
| **Weight Grid** | Auto-extracted barbell % table from WOD text (e.g. 65%→105% of 1RM) |
| **Recovery Block** | Metric row with icon + value + status badge + collapsible AI text |
| **Skeleton Loader** | Shimmer placeholder shown while Gist data loads |
| **Collapsible Section** | Header with ▸ chevron toggle, smooth height transition |
| **Workflow Card** | GitHub Actions trigger button with last-run status badge |
| **Barbell Chart** | Chart.js line chart, dark theme, neon-yellow line, selectable lift |
| **Reschedule Form** | Hidden inline form, date/time inputs, save → syncs to Garmin via API |
| **Progress Bar** | Horizontal bar with start/current/goal markers for 5K pace tracking |

---

## Event Card States

| State | Visual |
|-------|--------|
| Upcoming | Full opacity, accent-colored left border dot, expandable |
| Past | 55% opacity, muted border |
| Cancelled | 50% opacity, red border dot, "Undo" action visible |
| Loading | Skeleton shimmer replaces content |
| Empty | Icon + Dutch empty-state message |
| Error | Red alert banner with error text |

---

## Data Flow

```
GitHub Actions (cron scheduler)
  ↓
Python scripts (fetch / generate)
  ↓
GitHub Gist (multiple JSON files)
  ↓
Frontend JS (fetch via GitHub REST API)
  ↓
Rendered HTML + cached in Service Worker
  ↓
User's mobile or desktop browser
```

Automated refresh: every 4–6 hours via GitHub Actions cron.
Manual refresh: workflow trigger buttons in the app header.

---

## Core Data Entities

### CrossFit Event
```
id, date (YYYY-MM-DD), time (HH:MM), title,
signed_up_at, cancelled_at,
wod: { description, athlete_notes, skill_wod, strength_wod }
capacity: { current, max }
```

### Running Workout
```
date, session ("speed" | "long_run"), type, name, time,
total_distance_km, total_duration_min, description,
laps: [{ distance_m, pace_per_km, avg_hr }]
```

### Wellness (daily)
```
date, resting_hr, hrv, sleep_hrs, sleep_score,
ctl, atl, tsb, weight_kg, spo2,
skin_temp_c, endurance_score, hill_score   # Fenix 8 (Elevate V5 + Garmin scores), indien gesynct
```

### Body Composition (Withings)
```
date, weight_kg, fat_ratio, muscle_mass_kg,
hydration, bone_mass_kg, visceral_fat, nerve_health, pwv
```

### Barbell Lift
```
name (e.g. "Back Squat"), 1RM, 3RM, 5RM, last_updated
```

### Strava Activity
```
name, type, date, duration_min, distance_m,
avg_hr, max_hr, calories, suffer_score, perceived_exertion,
avg_watts   # running power (Fenix 8), indien opgenomen
```

### Intervals.icu Activity (extra t.o.v. Strava)
```
avg_watts (running power), stride_length_m, ground_contact_ms,
vert_oscillation_mm, vert_ratio_pct   # running dynamics (Fenix 8, zonder borstband)
```

---

## Localization

- **Language:** Dutch throughout (labels, buttons, messages, dates)
- **Date format:** Dutch locale (`nl-NL`) — e.g. "maandag 21 april"
- **Relative dates:** "Vandaag", "Morgen", "Overmorgen", "Gisteren"
- **Timezone:** Europe/Amsterdam, all times displayed in CET/CEST

---

## PWA Details

- **Standalone mode** — runs as installed app on mobile
- **Offline capable** — Service Worker caches assets (network-first strategy for API calls)
- **Icons** — SVG app icon + maskable icon variant
- **Theme color** — `#0d0d0d`
- **Display** — standalone (no browser chrome when installed)

---

## File Structure

```
sportbit/
├── index.html, style.css, sw.js, manifest.json
├── js/                     # PWA-modules: core, ui, push, state, wod, activities,
│                           # data, tabs, workflows, health, personal, running,
│                           # injuries, homeworkout, insights, main (laatst)
├── autosignup.py           # Huppa-inschrijving (+ vakantiemodus)
├── fetch_sugarwod.py       # SugarWOD-scrape + health-orchestratie
├── sugarwod_coach.py       # AI-coaching (herstel, workout-plannen, deload)
├── sugarwod_config.py      # Atletenprofiel en constanten
├── fetch_intervals.py / fetch_garmin.py / fetch_strava.py / fetch_withings.py / fetch_environmental.py
├── generate_*.py           # AI-generatie (hardlopen, open gym, thuistraining, context)
├── pr_alerts.py            # Push bij nieuw PR
├── notify.py / notify_failure.py  # Web Push + melding bij mislukte workflow
├── gist_utils.py, injuries.py
└── .github/workflows/      # Crons + handmatige workflows (concurrency per Gist-groep)
```
