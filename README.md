# CrossFit Auto Sign-Up for SportBit

Automated sign-up system for CrossFit classes at CrossFit Hilversum through SportBit. The bot automatically registers for predefined weekly training sessions, syncs them to Google Calendar, and sends push notifications.

## Project Description

This project automates the process of signing up for CrossFit WOD (Workout of the Day) classes on SportBit. It runs daily just after midnight Amsterdam time and attempts to register for classes according to a predefined weekly schedule. The system maintains state to track registrations and respects manual cancellations.

Key features:
- Automatic class registration up to 8 days in advance
- Google Calendar integration for registered classes
- Push notifications via Pushover
- State management to prevent re-registering after manual cancellations
- Weekly summary notifications every Sunday

Target users: CrossFit Hilversum members who want to automate their weekly class registrations.

## Configuration

The following secrets need to be configured as GitHub repository secrets:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for calendar access. Create a service account in Google Cloud Console and download the credentials
- **`CALENDAR_ID`** — Target Google Calendar ID where events will be created (use "primary" for main calendar or specific calendar ID)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing registration state between runs. Create a new secret gist and copy its ID from the URL
- **`GIST_TOKEN`** — GitHub personal access token with gist scope for reading/writing the state gist

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key from pushover.net dashboard
- **`PUSHOVER_API_TOKEN`** — Pushover application API token for sending notifications

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic Claude API key for automatic README generation (optional, only needed if using the update_readme workflow)

## Schedule

The automation runs on the following schedule via GitHub Actions:

### Daily Registration Runs
- **23:01 UTC** (00:01 Amsterdam winter time/CET) 
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

The workflow automatically adjusts for daylight saving time by running at both times. The script includes timezone validation to ensure it only executes once per day at the correct Amsterdam time.

### Weekly Summary
- **Every Sunday at 17:00 UTC** (18:00 Amsterdam time) — Sends a push notification with an overview of the upcoming week's classes and registration status

### Manual Execution
The workflow can also be triggered manually from the GitHub Actions tab. When run manually, it bypasses the timezone check using the `--force` flag.

### Scheduled Classes
The bot attempts to register for the following weekly schedule:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00