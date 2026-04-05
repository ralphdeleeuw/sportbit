# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for WOD (Workout of the Day) classes at CrossFit Hilversum on a weekly schedule. The system runs daily just after midnight Amsterdam time, checking upcoming classes and enrolling based on a predefined schedule.

## Project Description

This automation tool helps CrossFit Hilversum members secure their spots in popular WOD classes by automatically signing up as soon as registration opens. The system:

- Signs up for classes according to a configurable weekly schedule
- Syncs confirmed registrations to Google Calendar
- Sends push notifications via Pushover
- Tracks signup state to avoid duplicate registrations
- Detects manual cancellations and respects them
- Provides a weekly overview of upcoming classes every Sunday

The tool is designed for members who have a consistent training schedule and want to ensure they don't miss out on their preferred class times.

## Configuration

The following environment variables need to be configured as GitHub Secrets:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for calendar access. This should be the full JSON content from your service account key file
- **`CALENDAR_ID`** — Google Calendar ID where events will be created (use `primary` for your main calendar, or a specific calendar ID like `abc123@group.calendar.google.com`)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing signup state between runs. Create a private Gist and use its ID (the alphanumeric string in the URL)
- **`GIST_TOKEN`** — GitHub personal access token with `gist` scope for reading/writing to the state Gist

### Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving push notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic Claude API key for automatic README generation (optional, only needed if using the README update workflow)

## Schedule

The automation runs on the following schedule:

### Daily Sign-ups
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

The workflow automatically handles the timezone changes between summer and winter time. It runs just after midnight Amsterdam time to sign up for classes in the upcoming week.

### Weekly Summary
- **Every Sunday at 17:00 UTC** (18:00 Amsterdam time)

Sends a push notification with an overview of all registered classes for the upcoming week.

### Manual Runs
The workflow can also be triggered manually from the GitHub Actions UI. When run manually, it includes the `--force` flag to bypass the timezone check, allowing sign-ups at any time of day.

The default class schedule is configured in the code as:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00