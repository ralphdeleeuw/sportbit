# SportBit Auto Sign-Up for CrossFit Hilversum

This project automates the registration process for CrossFit WOD classes at CrossFit Hilversum through the SportBit platform. It runs daily via GitHub Actions to sign up for predefined weekly training slots, syncs registrations to Google Calendar, and sends notifications via push notifications.

## Project Description

The auto sign-up bot is designed for CrossFit Hilversum members who want to secure their spots in popular WOD (Workout of the Day) classes without manually checking the SportBit app. The system:

- Automatically registers for predefined training slots each week
- Detects and respects manual cancellations
- Syncs all registrations (both automatic and manual) to Google Calendar
- Sends push notifications for successful registrations
- Provides a weekly summary of upcoming training sessions
- Maintains state persistence through GitHub Gists

## Configuration

The following secrets must be configured in your GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit account password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for Calendar API access. This should be the full JSON content from a service account key file
- **`CALENDAR_ID`** — Google Calendar ID where events will be created (use `primary` for your main calendar or a specific calendar ID)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing registration state between runs. Create a new secret gist and use its ID
- **`GIST_TOKEN`** — GitHub personal access token with `gist` scope for reading/writing the state gist

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications (optional)
- **`PUSHOVER_API_TOKEN`** — Pushover application API token (optional)

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automatically generating README documentation (optional)

## Schedule

The automation runs on the following schedule via GitHub Actions:

### Daily Registration Runs
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

The workflow automatically handles the timezone difference between summer and winter time. It checks registrations for the next 8 days and signs up for these predefined slots:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

### Weekly Summary
- **Every Sunday at 17:00 UTC** (18:00 Amsterdam time)

Sends a push notification with an overview of all registrations for the upcoming week.

### Manual Trigger
The workflow can also be triggered manually from the GitHub Actions UI, which is useful for testing or immediate registration needs. Manual runs bypass the midnight timezone check.