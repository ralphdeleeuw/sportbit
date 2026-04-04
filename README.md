# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for CrossFit WOD classes at CrossFit Hilversum on a weekly schedule. The bot runs via GitHub Actions and supports Google Calendar synchronization and Pushover notifications.

## Project Description

This project automates the sign-up process for CrossFit classes at CrossFit Hilversum through the SportBit platform. It's designed for members who want to secure spots in popular classes that fill up quickly.

Key features:
- Automatically signs up for predefined weekly schedule
- Syncs confirmed registrations to Google Calendar
- Sends push notifications via Pushover
- Tracks sign-up state and detects manual cancellations
- Sends weekly overview of upcoming classes

Target users: CrossFit Hilversum members who want automated class registration.

## Configuration

The following secrets must be configured in your GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for calendar access. This should be the full JSON content from your service account key file
- **`CALENDAR_ID`** — Target Google Calendar ID (use "primary" for your main calendar)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing sign-up state between runs
- **`GIST_TOKEN`** — GitHub personal access token with gist permissions for updating the state

### Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automated README generation (optional)

## Schedule

The workflow runs automatically via GitHub Actions on the following schedule:

### Daily Sign-ups
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

The bot runs just after midnight Amsterdam time to sign up for classes up to 8 days in advance. The dual schedule ensures it always runs at 00:01 local Amsterdam time regardless of daylight saving changes.

### Weekly Summary
- **Sundays at 17:00 UTC** (18:00 Amsterdam time)

Sends a Pushover notification with an overview of all registered classes for the upcoming week.

### Manual Runs
You can also trigger the workflow manually from the GitHub Actions tab. When run manually, the timezone check is skipped using the `--force` flag.

The default class schedule is:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00