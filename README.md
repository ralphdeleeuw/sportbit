# SportBit Auto Sign-Up

Automated sign-up system for CrossFit Hilversum classes through SportBit. The system automatically registers for WOD classes according to a predefined weekly schedule, syncs them to Google Calendar, and sends push notifications.

## Project Description

This project automates the process of signing up for CrossFit classes at CrossFit Hilversum via the SportBit platform. It runs daily just after midnight Amsterdam time, checking for available classes up to 8 days ahead and automatically registering for classes that match the configured schedule. The system tracks which classes were signed up automatically versus manually, detects manual cancellations, and can optionally sync all registrations to Google Calendar.

Key features:
- Automatic daily sign-ups for predefined weekly schedule
- Manual enrollment detection and calendar sync
- Cancellation tracking to avoid re-registering
- Push notifications via Pushover
- Weekly summary reports
- State persistence using GitHub Gists
- Google Calendar integration

## Configuration

The following secrets need to be configured in your GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for Calendar API access. This should be the complete JSON content from your service account key file
- **`CALENDAR_ID`** — Google Calendar ID where events should be created (use `primary` for your main calendar or a specific calendar ID like `abc123@group.calendar.google.com`)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing signup state between runs. Create a private Gist and use its ID (the alphanumeric string in the URL)
- **`GIST_TOKEN`** — GitHub personal access token with `gist` scope for updating the state Gist

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Pushover API token/key for your application

### Documentation Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automatically generating README updates (optional, only needed if using the auto-documentation workflow)

## Schedule

The system runs on three different schedules via GitHub Actions:

### Daily Auto Sign-Up
- **Winter time (CET)**: Daily at 00:01 Amsterdam time (`cron: "1 23 * * *"`)
- **Summer time (CEST)**: Daily at 00:01 Amsterdam time (`cron: "1 22 * * *"`)

The workflow automatically adjusts for daylight saving time by having two cron schedules. Only the one matching the current Amsterdam time (00:01) will execute the sign-up process.

### Weekly Summary
- **Every Sunday at 18:00 Amsterdam time** (`cron: "0 17 * * 0"`)

Sends a push notification with an overview of all upcoming registrations for the week.

### Default Class Schedule
The system automatically signs up for the following weekly classes:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

The workflow checks up to 8 days ahead and will attempt to register for any matching slots that aren't already booked or manually cancelled.