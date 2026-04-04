# SportBit Auto Sign-Up for CrossFit Hilversum

This project provides automated sign-up functionality for CrossFit WOD classes at CrossFit Hilversum through the SportBit platform. It runs daily via GitHub Actions to register for scheduled weekly classes, with support for Google Calendar synchronization and push notifications.

## Project Description

The SportBit Auto Sign-Up tool automatically registers you for CrossFit classes according to a predefined weekly schedule. The system:

- Runs daily just after midnight Amsterdam time
- Signs up for classes up to 8 days in advance
- Tracks which classes were auto-registered vs manually registered
- Detects manual cancellations and skips re-registration
- Syncs successful registrations to Google Calendar
- Sends push notifications via Pushover
- Provides a weekly summary of upcoming registrations

### Target Users

This tool is designed for CrossFit Hilversum members who:
- Have a consistent weekly training schedule
- Want to ensure they get spots in popular classes
- Prefer automated registration over manual sign-ups

## Configuration

All secrets must be configured as GitHub repository secrets:

### Required Secrets

- **`SPORTBIT_USERNAME`** - Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** - Your SportBit login password

### Optional Secrets

- **`GOOGLE_CREDENTIALS`** - Google service account credentials JSON for Calendar API access. Create a service account in Google Cloud Console and paste the entire JSON content
- **`CALENDAR_ID`** - Google Calendar ID where events should be created (default: "primary")
- **`GIST_ID`** - GitHub Gist ID for storing persistent state between runs. Create a private Gist and use its ID
- **`GIST_TOKEN`** - GitHub personal access token with `gist` scope for reading/writing the state Gist
- **`PUSHOVER_USER_KEY`** - Your Pushover user key for receiving push notifications
- **`PUSHOVER_API_TOKEN`** - Pushover application API token
- **`ANTHROPIC_API_KEY`** - Anthropic API key for automated README generation (only needed if using the README update workflow)

## Schedule

The automation runs on the following schedule via GitHub Actions:

### Daily Sign-Up Runs
- **00:01 Amsterdam time** (daily) - Main registration run
  - `23:01 UTC` during winter time (CET)
  - `22:01 UTC` during summer time (CEST)
- The workflow automatically adjusts for daylight saving time by running at both times and checking the current Amsterdam time

### Weekly Summary
- **18:00 Amsterdam time on Sundays** - Sends a push notification with all upcoming registrations for the week

### Manual Runs
- The workflow can be manually triggered from the GitHub Actions UI
- Manual runs bypass the timezone check using the `--force` flag

### Class Schedule
The default weekly training schedule is configured in the code:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

The system will attempt to register for these classes when they become available within the 8-day look-ahead window.