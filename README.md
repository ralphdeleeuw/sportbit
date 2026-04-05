# SportBit Auto Sign-Up for CrossFit Hilversum

Automated sign-up system for CrossFit classes at CrossFit Hilversum through the SportBit platform. The system runs daily after midnight Amsterdam time and automatically registers for predefined weekly training sessions.

## Project Description

This project automates the class registration process for CrossFit Hilversum members. It:
- Signs up for WOD (Workout of the Day) classes according to a weekly schedule
- Syncs registered classes to Google Calendar
- Sends push notifications for successful registrations
- Tracks registration state and manual cancellations via GitHub Gist
- Provides a weekly summary of upcoming classes every Sunday

The system is designed for members who have a consistent training schedule and want to ensure they secure spots in popular classes that fill up quickly.

## Configuration

The following secrets need to be configured in your GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** - Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** - Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** - Google service account credentials in JSON format for calendar access
- **`CALENDAR_ID`** - Target Google Calendar ID where events will be created (use "primary" for main calendar)

### State Management
- **`GIST_ID`** - GitHub Gist ID for storing registration state between runs
- **`GIST_TOKEN`** - GitHub personal access token with gist scope for reading/writing the state file

### Push Notifications
- **`PUSHOVER_USER_KEY`** - Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** - Pushover application API token

### Documentation Generation
- **`ANTHROPIC_API_KEY`** - Anthropic API key for automatic README generation (optional)

## Schedule

The automation runs on the following schedule via GitHub Actions:

### Daily Sign-Up Runs
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

The workflow automatically adjusts for daylight saving time by running at both times. The script includes a timezone check to ensure it only executes once per day after midnight Amsterdam time.

### Weekly Summary
- **Every Sunday at 17:00 UTC** (18:00 Amsterdam time)

Sends a push notification with an overview of all registered classes for the upcoming week.

### Default Class Schedule
The system registers for the following weekly classes:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

### Manual Execution
The workflow can also be triggered manually from the GitHub Actions tab, which bypasses the timezone check for immediate execution.