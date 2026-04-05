# SportBit Auto Sign-Up for CrossFit Hilversum

An automated sign-up system for CrossFit WOD classes at CrossFit Hilversum via the SportBit platform. The system automatically registers you for classes according to a predefined weekly schedule, syncs with Google Calendar, and sends push notifications.

## Project Description

This project automates the tedious process of signing up for CrossFit classes. It runs daily just after midnight Amsterdam time and:

- Automatically signs up for WOD classes based on your weekly schedule
- Syncs successful registrations to Google Calendar
- Sends push notifications via Pushover
- Tracks sign-up state to avoid duplicate registrations
- Detects manual cancellations and respects them
- Provides a weekly summary of upcoming classes every Sunday

The system is designed for members of CrossFit Hilversum who want to secure their spots in popular classes without having to remember to sign up manually.

## Configuration

The following environment variables need to be configured as GitHub Secrets:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON (for calendar sync). Should be the full JSON content from your service account key file
- **`CALENDAR_ID`** — Google Calendar ID where events will be created (e.g., `primary` for your main calendar or a specific calendar ID)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing sign-up state between runs. Create a private gist and use its ID
- **`GIST_TOKEN`** — GitHub personal access token with gist permissions for updating the state

### Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving push notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token

### Documentation
- **`ANTHROPIC_API_KEY`** — Anthropic (Claude) API key for automatic README generation

## Schedule

The automated workflow runs at three different times:

1. **Daily at 00:01 Amsterdam time** — Main sign-up run
   - Runs twice daily to handle daylight saving time changes:
     - `23:01 UTC` (for Amsterdam winter time/CET)
     - `22:01 UTC` (for Amsterdam summer time/CEST)
   - Automatically signs up for classes in the next 8 days according to the predefined schedule

2. **Sundays at 18:00 Amsterdam time** — Weekly summary
   - Sends a push notification with all your registrations for the upcoming week
   - Includes both auto-registered and manually registered classes

3. **Manual trigger** — Can be run anytime via GitHub Actions UI
   - Useful for testing or immediate sign-ups
   - Uses the `--force` flag to skip timezone checks

The default weekly schedule (configured in `autosignup.py`) is:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00