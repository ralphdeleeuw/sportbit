# SportBit Auto Sign-Up for CrossFit Hilversum

Automated sign-up system for CrossFit WOD classes at CrossFit Hilversum via SportBit. Runs daily on GitHub Actions to automatically register for scheduled classes, sync to Google Calendar, and send push notifications.

## Project Description

This project automates the process of signing up for CrossFit classes on SportBit. It:
- Automatically signs up for predefined weekly training sessions
- Syncs confirmed registrations to Google Calendar
- Sends push notifications via Pushover when successfully registered
- Tracks sign-up state to avoid duplicate registrations
- Detects manual cancellations and updates calendar accordingly
- Provides a weekly summary of upcoming classes every Sunday

The system is designed for CrossFit Hilversum members who want to automate their regular training schedule.

## Configuration

The following secrets need to be configured in your GitHub repository settings:

### SportBit Authentication
- **`SPORTBIT_USERNAME`** — Your SportBit login username
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON (for calendar sync)
- **`CALENDAR_ID`** — Google Calendar ID where events should be created (use "primary" for main calendar)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing sign-up state between runs
- **`GIST_TOKEN`** — GitHub personal access token with gist permissions

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automated README updates (optional)

## Schedule

The workflow runs automatically at three different times:

### Daily Sign-ups
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

The script runs just after midnight Amsterdam time to sign up for classes in the coming week. It automatically adjusts for daylight saving time by having two cron schedules.

### Weekly Summary
- **17:00 UTC on Sundays** (18:00 Amsterdam time)

Sends a push notification with an overview of all upcoming registrations for the week.

The default weekly training schedule is:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

The script looks ahead 8 days and will sign up for any scheduled classes that fall within that window.