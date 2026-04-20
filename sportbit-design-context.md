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
| Running goal | Improve 5K from 28:00 → 26:00 |
| Strength focus | Back squat, deadlift, Olympic lifts |
| Language | Dutch (nl) |
| Timezone | Europe/Amsterdam (CET/CEST) |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vanilla JS, single HTML file (SPA) |
| Charts | Chart.js v4 |
| Markdown rendering | marked.js |
| PWA | Service Worker + Web App Manifest |
| Backend/automation | Python 3.12, GitHub Actions (cron) |
| Data storage | GitHub Gist (JSON files, no database) |
| AI coaching | Anthropic Claude API |
| Notifications | Pushover API |
| Calendar sync | Google Calendar API |

**Data sources integrated:**
- SugarWOD (CrossFit WODs, athlete notes, PRs)
- Strava (running & outdoor activities)
- Intervals.icu / Garmin Connect (wellness: HRV, sleep, training load)
- Withings (body composition: weight, fat %, muscle mass)
- MyFitnessPal (nutrition diary)
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

Single-page app — no routing. All sections on one scrollable page with collapsible panels.

### 1. Configuration Bar (sticky top)
- GitHub Gist ID input + Personal Access Token input
- Last updated timestamp
- Four workflow trigger buttons:
  - ⚡ **Inschrijven** — trigger auto-signup
  - ↻ **SugarWOD Sync** — fetch WOD + AI coaching
  - ♥ **Health Refresh** — sync Strava / Intervals / Withings
  - 🏃 **Hardloopplan** — generate running plan

### 2. Stats Bar
- 3-column grid of key numbers:
  - Upcoming classes count
  - Past classes count
  - Third metric (configurable)

### 3. Recovery Status Block
- Resting HR, HRV, sleep quality, TSB (Training Stress Balance)
- Color-coded badges: Fresh / Neutral / Fatigued
- AI-generated recovery advice (rendered markdown)
- Collapsible

### 4. Upcoming Events
- "**+ Toevoegen**" (Add Event) button
- Event cards (CrossFit classes, personal events, running workouts)
- Each card shows:
  - Colored status dot
  - Title, date/time, relative label ("Morgen", "Overmorgen")
  - Capacity badge (e.g. "10/15")
  - Weather/air quality badge
  - Expandable: WOD description, athlete notes, barbell weight suggestions
  - Inline Strava/Intervals activity summary for same day
  - Running plan details (distance, pace, lap splits)

### 5. Cancelled Events
- Last 8 days of cancellations
- "Undo" button to restore

### 6. Past Activities
- Standalone activities without an associated class
- CrossFit completion summaries

### 7. Running Plan Block
- 5K progress bar (current pace → goal 26:00)
- List of scheduled runs with lap/split data
- 📅 Reschedule button + inline date/time form

### 8. Strength Training
- Personal Records table (Back Squat, Deadlift, Bench Press, etc.)
- Barbell Lifts table: 1RM per lift + percentage grid (65–105%)
- Trend chart (Chart.js line chart, lift selector dropdown)

### 9. Benchmark Workouts
- Tabbed interface by WOD type (Amrap, Emom, Chipper, etc.)
- Results table: benchmark name / result / scaling / date

### 10. Data Sources (debug panel)
- Collapsible tables showing raw data from each integration
- API status, latest sync timestamps

### 11. Footer
- Last sync time
- Data source attribution
- Workflow status indicators

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
ctl, atl, tsb, weight_kg, spo2
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
avg_hr, max_hr, calories, suffer_score, perceived_exertion
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
├── index.html                    # Main SPA (~3900 lines)
├── manifest.json                 # PWA manifest
├── sw.js                         # Service Worker
├── icon.svg / icon-maskable.svg  # App icons
│
├── autosignup.py                 # Auto class registration
├── fetch_sugarwod.py             # WOD + AI coaching data
├── fetch_intervals.py            # Garmin/wellness data
├── fetch_strava.py               # Running activities
├── fetch_withings.py             # Body composition
├── fetch_myfitnesspal.py         # Nutrition diary
├── fetch_environmental.py        # Weather + air quality
│
├── generate_fitness_context.py   # Aggregate athlete data for AI
├── generate_running_workout.py   # Claude-powered run plan generator
├── reschedule_running_workout.py # Date override + Garmin sync
├── send_preworkout_briefing.py   # 30min pre-class push notification
├── google_calendar_sync.py       # Google Calendar integration
│
├── .github/workflows/            # GitHub Actions automation
│   ├── autosignup.yml
│   ├── fetch_sugarwod.yml
│   ├── fetch_health_data.yml
│   ├── generate_running_workout.yml
│   └── [6 more workflows]
│
├── requirements.txt
└── README.md
```
