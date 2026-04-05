# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for CrossFit WOD classes at CrossFit Hilversum on a predefined weekly schedule. The script runs daily via GitHub Actions, detects available classes, handles registrations, syncs to Google Calendar, and sends push notifications.

## Project Description

This automation tool is designed for CrossFit Hilversum members who want to secure their spots in popular WOD (Workout of the Day) classes. The script:

- Automatically signs up for classes based on a weekly schedule
- Syncs confirmed registrations to Google Calendar
- Sends push notifications via Pushover
- Tracks sign-up state to prevent duplicate registrations
- Detects manual cancellations and respects them
- Provides a weekly summary of upcoming classes

The script is particularly useful for members with consistent training schedules who want to ensure they get spots in classes that tend to fill up quickly.

## Configuration

The following environment variables must be set as GitHub Secrets:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for calendar access. This should be the entire JSON content from the service account key file
- **`CALENDAR_ID`** — Google Calendar ID where events should be created (use `primary` for your main calendar)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing sign-up state between runs. Create an empty private gist and use its ID
- **`GIST_TOKEN`** — GitHub personal access token with gist permissions for updating the state file

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automatic README generation (optional, only needed for the update_readme workflow)

## Schedule

The automation runs on three schedules via GitHub Actions:

### Daily Auto Sign-Up
- **Winter time (CET)**: Daily at 00:01 Amsterdam time (`cron: "1 23 * * *"`)
- **Summer time (CEST)**: Daily at 00:01 Amsterdam time (`cron: "1 22 * * *"`)

The script automatically adjusts for daylight saving time by running at both possible UTC times. Only the run that occurs after midnight Amsterdam time will proceed with sign-ups.

### Weekly Summary
- **Every Sunday at 18:00 Amsterdam time** (`cron: "0 17 * * 0"`)

Sends a Pushover notification with an overview of all upcoming registered classes for the week.

### Manual Trigger
The workflow can also be triggered manually from the GitHub Actions UI, which is useful for testing or immediate sign-ups. Manual runs bypass the midnight time check.

### Default Class Schedule
The script signs up for the following weekly classes by default:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

This schedule is defined in the `SCHEDULE` variable in `autosignup.py` and can be modified as needed.