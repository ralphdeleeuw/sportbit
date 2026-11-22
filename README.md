# SportBit (RalphFit)

Persoonlijk CrossFit- en hardloopdashboard voor CrossFit Hilversum. Python-scripts
halen data op (Huppa, SugarWOD, Garmin/intervals.icu, Strava, Withings, weer/lucht),
bewaren die in één GitHub Gist en laten AI-coaches (Claude) trainingsadvies en
hardloopschema's maken. De PWA (`index.html` + `js/`) toont alles op de telefoon.

## Wat het doet

- **Automatisch inschrijven** voor de vaste lessen (ma 20:00, wo 08:00, do 20:00,
  zo 09:00) via Huppa, incl. Google Agenda-sync. **Vakantiemodus** pauzeert dit
  voor een datumbereik.
- **Data verzamelen** elke 4 uur (health) en dagelijks (SugarWOD).
- **AI-coaching on-demand**: herstel-advies, workout-plannen, hardloopschema,
  open gym-programma, thuistraining (alleen via knoppen in de app — kostenbesparing).
- **Weekreview** elke zondagavond: cijfers + kort AI-advies, als pushmelding.
- **Pushmeldingen** bij nieuwe PR's, mislukte workflows (max. 1× per 12 uur per
  workflow), pre-workout briefing en weekoverzicht.

## De app

| Tab | Inhoud |
|-----|--------|
| Vandaag | Dagadvies (vol gas / rustig aan / rust), weekreview, blessures, herstel + AI-coach |
| Schema | Komende lessen, runs en eigen events; nog niet ingeschreven slots |
| Hardlopen | Prestatievoorspeller (5K + 12-minutentest), hardloopplan, analyses |
| CrossFit | PR's, benchmarks, barbell-progressie |
| Acties | Databronnen-versheid, trainingsbelasting, blessures, vakantiemodus, workflowknoppen |

Werkt ook offline: de laatst geladen data staat lokaal (IndexedDB) en wordt bij
opstarten direct getoond. Trek omlaag op Vandaag/Schema om te verversen.

## Workflows (GitHub Actions)

| Workflow | Wanneer |
|----------|---------|
| `autosignup.yml` | dagelijks 23:13, 01:41 en 03:17 UTC + weekoverzicht zo 17:03 UTC |
| `fetch_health_data.yml` | elke 4 uur op :13 |
| `fetch_sugarwod.yml` | dagelijks 04:37 UTC |
| `cancel_running_workout.yml` | elke 4 uur op :43 |
| `sync_to_gcal.yml` | dagelijks 07:22 UTC |
| `preworkout_briefing.yml` | 30 min vóór elke les |
| `weekly_review.yml` | zondag 17:23 UTC |
| overige | alleen handmatig / via de app |

Workflows die hetzelfde Gist-bestand schrijven delen een `concurrency`-groep
(`gist-wod`, `gist-running`, `gist-state`), zodat ze elkaars wijzigingen niet
overschrijven. Crons staan bewust niet op `:00` (GitHub vertraagt die runs).

## Secrets

`GIST_ID`, `GIST_TOKEN`, `ANTHROPIC_API_KEY`, `VAPID_PRIVATE_KEY`,
`VAPID_CLAIMS_EMAIL`, `HUPPA_*`, `SUGARWOD_*`, `GARMIN_*`, `INTERVALS_*`,
`STRAVA_*`, `WITHINGS_*`, `WAQI_API_TOKEN`, `GOOGLE_CREDENTIALS`, `CALENDAR_ID`.

Het GitHub-token in de app moet een **fine-grained token** zijn met alleen
*Actions: read/write* op deze repo en *Gists: read/write* (uitleg staat in de app
onder Acties → Instellingen).

## Code-indeling

- `js/` — PWA, één bestand per onderdeel; `main.js` laadt als laatste.
- `fetch_sugarwod.py` — SugarWOD-scrape + health-orchestratie;
  `sugarwod_coach.py` (AI-coaching) en `sugarwod_config.py` (profiel/constanten).
- `fetch_*.py` — databronnen; `generate_*.py` — AI-generatie; `gist_utils.py`,
  `notify.py` — gedeelde helpers.
- `weekly_review.py`, `pr_alerts.py`, `notify_failure.py` — review en meldingen.
