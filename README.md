# CrossFit Hilversum Auto Sign-Up

Automated sign-up system for CrossFit WOD classes at CrossFit Hilversum via SportBit. The script runs daily after midnight to register for classes according to a predefined schedule, with optional Google Calendar integration and push notifications.

## Project Description

This project automates the sign-up process for CrossFit classes at CrossFit Hilversum through the SportBit platform. It:

- Automatically signs up for WOD classes based on a weekly schedule
- Syncs confirmed registrations to Google Calendar
- Sends push notifications via Pushover
- Tracks sign-up state to handle manual cancellations
- Provides a weekly summary of upcoming classes every Sunday

The default schedule includes:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

## Configuration

The following secrets need to be configured as environment variables or GitHub Secrets:

### Required Secrets

- **`SPORTBIT_USERNAME`** - Your SportBit login username
- **`SPORTBIT_PASSWORD`** - Your SportBit login password

### Optional Secrets

- **`GOOGLE_CREDENTIALS`** - Google service account credentials JSON for calendar sync. Can be either a file path or the raw JSON content
- **`CALENDAR_ID`** - Google Calendar ID where events should be created (defaults to 'primary')
- **`GIST_ID`** - GitHub Gist ID for storing sign-up state between runs
- **`GIST_TOKEN`** - GitHub personal access token with gist permissions for state management
- **`PUSHOVER_USER_KEY`** - Pushover user key for push notifications
- **`PUSHOVER_API_TOKEN`** - Pushover API token for sending notifications
- **`ANTHROPIC_API_KEY`** - Anthropic API key for automatically generating README documentation

## Schedule

The automated workflow runs on the following schedule:

### Daily Sign-ups
- **23:01 UTC** (00:01 Amsterdam time during CET/winter)
- **22:01 UTC** (00:01 Amsterdam time during CEST/summer)

The script includes timezone validation to ensure it only executes once per day just after midnight Amsterdam time. This prevents duplicate runs when switching between summer and winter time.

### Weekly Summary
- **Every Sunday at 17:00 UTC** (18:00 Amsterdam time)

Sends a push notification with an overview of all registered classes for the upcoming week.

### Manual Execution
The workflow can also be triggered manually from the GitHub Actions UI. When run manually, use the `--force` flag to bypass the timezone check.