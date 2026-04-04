# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for CrossFit WOD classes at CrossFit Hilversum using the SportBit platform. The system runs daily via GitHub Actions, checking for upcoming classes and registering according to a predefined weekly schedule.

## Project Description

This project automates the sign-up process for CrossFit classes at CrossFit Hilversum. It:
- Automatically signs up for classes based on a weekly schedule
- Syncs confirmed registrations to Google Calendar
- Sends push notifications via Pushover
- Tracks sign-up state to avoid duplicate registrations
- Detects manual cancellations and respects them
- Provides a weekly summary of upcoming classes

The system is designed for members who want to ensure they get spots in popular classes without having to manually check and register each time.

## Configuration

The following environment variables (secrets) need to be configured:

### SportBit Credentials
- **SPORTBIT_USERNAME** — Your SportBit login username (email address)
- **SPORTBIT_PASSWORD** — Your SportBit login password

### Google Calendar Integration
- **GOOGLE_CREDENTIALS** — Google service account credentials in JSON format for calendar access
- **CALENDAR_ID** — Google Calendar ID where events should be created (use "primary" for main calendar)

### State Management
- **GIST_ID** — GitHub Gist ID for storing registration state between runs
- **GIST_TOKEN** — GitHub personal access token with gist permissions

### Push Notifications
- **PUSHOVER_USER_KEY** — Your Pushover user key for receiving notifications
- **PUSHOVER_API_TOKEN** — Pushover application API token

### README Generation
- **ANTHROPIC_API_KEY** — Anthropic API key for automated README generation (optional)

## Schedule

The automated workflow runs at three different times:

### Daily Sign-Up Runs
- **00:01 Amsterdam time (CET)** — `cron: "1 23 * * *"`
- **00:01 Amsterdam time (CEST)** — `cron: "1 22 * * *"`

The system includes both winter and summer time schedules to ensure it always runs just after midnight Amsterdam time, regardless of daylight saving changes. The script includes a timezone check to prevent duplicate runs.

### Weekly Summary
- **Every Sunday at 18:00 Amsterdam time** — `cron: "0 17 * * 0"`

Sends a push notification with an overview of all upcoming registered classes for the week.

### Class Schedule
The system automatically signs up for classes at these times:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

The script looks 8 days ahead by default and will attempt to register for any matching classes in the configured schedule.