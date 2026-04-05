# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for CrossFit WOD classes at CrossFit Hilversum according to a predefined weekly schedule. The system runs daily via GitHub Actions, tracks sign-up state, syncs with Google Calendar, and sends push notifications.

## Project Description

This project automates the sign-up process for CrossFit classes at CrossFit Hilversum through the SportBit platform. It's designed for members who want to ensure they're registered for their regular training sessions without having to manually sign up each time.

Key features:
- Automated daily sign-ups for predefined weekly schedule
- State tracking to prevent duplicate sign-ups and respect manual cancellations
- Google Calendar integration for automatic event creation
- Push notifications via Pushover
- Weekly summary reports
- Manual enrollment detection and calendar sync

## Configuration

The following secrets need to be configured in GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google Service Account credentials in JSON format. This should be the complete JSON key file content from a Google Cloud service account with Calendar API access
- **`CALENDAR_ID`** — Google Calendar ID where events should be created (e.g., "primary" for the main calendar or a specific calendar ID)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing sign-up state between runs. Create a new private Gist and use its ID
- **`GIST_TOKEN`** — GitHub Personal Access Token with `gist` scope for reading/writing to the Gist

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automatic README generation (optional, only needed if using the README update workflow)

## Schedule

The automation runs on the following schedule via GitHub Actions:

### Daily Sign-Up Runs
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

These runs execute just after midnight Amsterdam time to sign up for classes in the upcoming week (default: 8 days ahead). The dual schedule ensures the script runs at the correct Amsterdam time regardless of daylight saving changes.

### Weekly Summary
- **Sundays at 17:00 UTC** (18:00 Amsterdam time)

Sends a push notification with an overview of all registered classes for the upcoming week.

### Manual Triggers
The workflow can also be triggered manually from the GitHub Actions UI with the `--force` flag to bypass timezone checks.

### Default Class Schedule
The script automatically signs up for the following weekly classes:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

This schedule is defined in the `SCHEDULE` variable in `autosignup.py` and can be modified as needed.