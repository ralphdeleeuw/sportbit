# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for CrossFit WOD classes at CrossFit Hilversum on a predefined weekly schedule. The system runs daily via GitHub Actions and manages state through a GitHub Gist to track signed-up and cancelled events.

## Project Description

This project automates the registration process for CrossFit classes at CrossFit Hilversum through the SportBit platform. It's designed for athletes who have a consistent weekly training schedule and want to ensure they secure spots in popular classes.

Key features:
- Automatically signs up for classes based on a configurable weekly schedule
- Syncs registered classes to Google Calendar
- Detects and tracks manual cancellations
- Sends weekly summaries of upcoming classes
- Supports dry-run mode for testing

## Configuration

The following secrets must be configured in your GitHub repository:

### SportBit Credentials
- **SPORTBIT_USERNAME** — Your SportBit login username (email address)
- **SPORTBIT_PASSWORD** — Your SportBit login password

### Google Calendar Integration
- **GOOGLE_CREDENTIALS** — Google service account credentials JSON for calendar access. This should be the full JSON content of your service account key file
- **CALENDAR_ID** — Target Google Calendar ID where events will be created (use "primary" for your main calendar)

### State Management
- **GIST_ID** — GitHub Gist ID for storing signup state between runs. Create a private Gist and use its ID
- **GIST_TOKEN** — GitHub personal access token with gist scope for reading/writing the state Gist

### Notifications (Optional)
- **PUSHOVER_USER_KEY** — Pushover user key for push notifications (if using Pushover)
- **PUSHOVER_API_TOKEN** — Pushover application API token (if using Pushover)

### README Generation
- **ANTHROPIC_API_KEY** — Anthropic API key for automatically generating README documentation

## Schedule

The workflow runs on the following schedule:

### Daily Sign-ups
- **23:01 UTC** (00:01 Amsterdam winter time/CET) — Runs the auto-signup process
- **22:01 UTC** (00:01 Amsterdam summer time/CEST) — Runs the auto-signup process

The dual schedule ensures the script runs just after midnight Amsterdam time throughout the year, automatically adjusting for daylight saving time changes.

### Weekly Summary
- **Sundays at 17:00 UTC** (18:00 Amsterdam time) — Sends a weekly overview of upcoming registered classes

### Manual Runs
The workflow can also be triggered manually from the GitHub Actions UI using the "workflow_dispatch" event. Manual runs automatically include the `--force` flag to bypass timezone checks.

### Default Class Schedule
The script is configured to sign up for classes at these times:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

Classes are checked up to 8 days in advance, ensuring you're always registered for the upcoming week's sessions.