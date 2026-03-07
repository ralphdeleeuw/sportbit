# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for CrossFit WOD classes at CrossFit Hilversum on a predefined weekly schedule. The system runs daily via GitHub Actions and maintains state to handle manual cancellations intelligently.

## Project Description

This project automates the sign-up process for CrossFit classes through the SportBit platform. It runs automatically every day at midnight (Amsterdam time) and:

- Signs up for predefined weekly classes (Monday 20:00, Wednesday 08:00, Thursday 20:00, Saturday 09:00)
- Syncs confirmed sign-ups to Google Calendar
- Sends push notifications via Pushover when successfully signed up
- Tracks which classes were manually cancelled to avoid re-signing up
- Handles waitlists and full classes gracefully

The system is designed for CrossFit Hilversum members who want to automate their weekly class registrations while maintaining flexibility to manually cancel when needed.

## Configuration

All configuration is done through GitHub Secrets. The following secrets must be set:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google Service Account credentials as a JSON string. This enables the script to create calendar events for successful sign-ups
- **`CALENDAR_ID`** — The Google Calendar ID where events should be created (use "primary" for your main calendar)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing persistent state between runs. Create a private Gist and use its ID
- **`GIST_TOKEN`** — GitHub Personal Access Token with `gist` scope to read/write the state Gist

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automatically generating README documentation (used by the update_readme workflow)

## Schedule

The auto sign-up workflow runs daily via GitHub Actions at midnight Amsterdam time. The schedule accommodates both winter (CET) and summer (CEST) time:

- **Winter time (CET)**: Runs at `23:01 UTC` (00:01 Amsterdam time)
- **Summer time (CEST)**: Runs at `22:01 UTC` (00:01 Amsterdam time)

The workflow can also be triggered manually through the GitHub Actions UI using the "Run workflow" button.

### Weekly Class Schedule

The script automatically signs up for the following classes each week:
- **Monday** at 20:00
- **Wednesday** at 08:00
- **Thursday** at 20:00
- **Saturday** at 09:00

The script looks 8 days ahead and will sign up for any scheduled classes that match this pattern. If you're already signed up or on a waitlist, it will skip that class. If you manually cancel a class after the script signed you up, it will remember this and never attempt to sign up for that specific class instance again.