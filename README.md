# SportBit Auto Sign-Up for CrossFit Hilversum

A GitHub Actions workflow that automatically signs up for CrossFit WOD classes at CrossFit Hilversum through the SportBit platform. The system runs daily, checks for scheduled classes up to 8 days ahead, and handles sign-ups with state management, Google Calendar integration, and push notifications.

## Project Description

This project automates the repetitive task of signing up for CrossFit classes on SportBit. It's designed for CrossFit Hilversum members who attend classes on a regular weekly schedule and want to ensure they secure their spots without manual intervention.

Key features:
- **Automated sign-ups** for predefined weekly schedule
- **State management** to track signed-up classes and respect manual cancellations
- **Google Calendar sync** to automatically add confirmed classes to your calendar
- **Push notifications** via Pushover when successfully signed up
- **Dry-run mode** for testing without making actual sign-ups

## Configuration

The following secrets need to be configured in your GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials in JSON format. This should be the full JSON content of your service account key file, which enables the workflow to create calendar events
- **`CALENDAR_ID`** — The ID of the Google Calendar where events should be created. Use `"primary"` for your main calendar, or a specific calendar ID like `"abc123@group.calendar.google.com"`

### State Management
- **`GIST_ID`** — The ID of a GitHub Gist used to persist state between workflow runs. Create a private Gist and copy its ID from the URL
- **`GIST_TOKEN`** — A GitHub personal access token with `gist` scope to read/write the state Gist

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Your Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** — Claude API key for automatically generating and updating the README documentation

## Schedule

The workflow runs automatically via GitHub Actions on the following schedule:

- **Daily at 00:01 Amsterdam time** — The workflow is configured with two cron schedules to handle daylight saving time:
  - `"1 23 * * *"` — 00:01 CET (Central European Time - winter)
  - `"1 22 * * *"` — 00:01 CEST (Central European Summer Time)

When triggered, the workflow:
1. Checks for classes in the next 8 days that match your weekly schedule
2. Detects any manual cancellations (classes you cancelled after the script signed you up)
3. Signs up for available classes that haven't been manually cancelled
4. Sends push notifications for successful sign-ups
5. Creates Google Calendar events for each confirmed class

The weekly class schedule is defined in the code as:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

You can also trigger the workflow manually through the GitHub Actions UI using the "workflow_dispatch" event.