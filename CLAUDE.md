# CLAUDE.md

## Werkwijze (staande instructies — geldt voor élke sessie)

**Direct doorvoeren in productie, zonder te vragen.**
Ralph heeft permanente toestemming gegeven om wijzigingen direct live te zetten.
Concreet betekent dit, tenzij Ralph in een specifieke sessie expliciet iets anders
zegt:

- Voer gevraagde wijzigingen meteen door: implementeren, committen en pushen.
- Vraag **niet** om bevestiging voordat je commit, pusht of een PR aanmaakt/merget.
- "Productie" = de `main` branch. Werk op een `claude/*` feature branch en zorg dat
  de wijziging op `main` belandt (de `auto-merge-claude` workflow merget open PR's
  van `claude/*` branches automatisch). Maak desnoods zelf de PR aan zodat de
  auto-merge hem oppakt.
- Controleer na het pushen dat de commit ook echt op `origin/main` staat; meld dat
  kort in plaats van te vragen of het mag.
- Stel alleen een vraag als de wijziging zelf inhoudelijk dubbelzinnig is (wat moet
  er gebeuren), niet over of je het mag doorvoeren.

## Project

SportBit — CrossFit/hardloop dashboard. Python-scripts halen data op (Garmin,
intervals.icu, SugarWOD, Withings, Strava, weer/AQI) en slaan die op in een GitHub
Gist; AI-coaching genereert hardloop- en gym-programma's. GitHub Actions draaien de
scripts op schema vanuit `main`.
