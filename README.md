# SportBit Auto Sign-Up

Automated sign-up system for CrossFit Hilversum classes via SportBit. Runs daily after midnight Amsterdam time to register for upcoming WOD (Workout of the Day) classes according to a predefined schedule.

## Project Description

This project automatically signs up for CrossFit classes at CrossFit Hilversum through the SportBit platform. It:

- Signs up for classes according to a weekly schedule (Monday 20:00, Wednesday 08:00, Thursday 20:00, Saturday 09:00, Sunday 09:00)
- Syncs confirmed registrations to Google Calendar
- Sends push notifications via Pushover when successfully registered
- Tracks registration state in a GitHub Gist to avoid duplicate sign-ups
- Detects manual cancellations and respects them
- Sends a weekly summary every Sunday at 18:00 Amsterdam time

The system is designed for members who want to ensure their spot in popular classes without having to manually register each time.

## Configuration

The following secrets need to be configured in your GitHub repository:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username/email
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for calendar access
- **`CALENDAR_ID`** — Google Calendar ID where events should be created (use "primary" for main calendar)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing registration state between runs
- **`GIST_TOKEN`** — GitHub personal access token with gist scope for updating the state

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automatic README generation (optional)

## Schedule

The automation runs on the following schedule:

### Daily Sign-Up Runs
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

These dual schedules ensure the script runs just after midnight Amsterdam time year-round, accounting for daylight saving time changes. The script checks up to 8 days ahead and signs up for classes matching the configured weekly schedule.

### Weekly Summary
- **Every Sunday at 17:00 UTC** (18:00 Amsterdam time)

Sends a Pushover notification with an overview of all upcoming registrations for the week.

### Manual Trigger
The workflow can also be triggered manually from the GitHub Actions UI. When triggered manually, the `--force` flag is automatically applied to skip the timezone check, allowing runs at any time of day.