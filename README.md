# SportBit Auto Sign-Up for CrossFit Hilversum

Automated sign-up system for CrossFit WOD classes at CrossFit Hilversum via SportBit. The system automatically enrolls you in your preferred weekly training schedule, syncs confirmed registrations to Google Calendar, and sends push notifications to your phone.

## Project Description

This project automates the class registration process for CrossFit Hilversum members who have a consistent weekly training schedule. Instead of manually signing up for each class, the system:

- Automatically signs up for your predefined weekly schedule (configurable days and times)
- Syncs successful registrations to your Google Calendar
- Sends push notifications to your phone via Pushover
- Tracks registration state to prevent duplicate sign-ups
- Detects manual cancellations and respects them
- Provides a weekly summary of all upcoming registrations

The system is designed for members who want to secure their spots in popular classes without the hassle of manual registration.

## Configuration

The following secrets need to be configured in your GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** — Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** — Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for calendar access. Create a service account in Google Cloud Console and download the JSON key file
- **`CALENDAR_ID`** — Target Google Calendar ID where events will be created (use "primary" for your main calendar or a specific calendar ID)

### State Management
- **`GIST_ID`** — GitHub Gist ID for persisting registration state between runs. Create a new secret Gist and copy its ID from the URL
- **`GIST_TOKEN`** — GitHub personal access token with `gist` scope for reading/writing the state Gist

### Push Notifications
- **`PUSHOVER_USER_KEY`** — Your Pushover user key (found in your Pushover account settings)
- **`PUSHOVER_API_TOKEN`** — Pushover application API token (create an application in your Pushover account)

### README Generation
- **`ANTHROPIC_API_KEY`** — Anthropic Claude API key for automatically generating README documentation (optional, only needed for README updates)

## Schedule

The workflow runs on the following schedule:

### Daily Sign-Up Runs
- **00:01 Amsterdam time** (daily) — Main registration run that signs up for classes in the next 8 days
  - Winter time (CET): Runs at 23:01 UTC
  - Summer time (CEST): Runs at 22:01 UTC
  - The dual schedule ensures consistent execution at 00:01 Amsterdam time year-round

### Weekly Summary
- **Sunday 18:00 Amsterdam time** — Sends a push notification with an overview of all registrations for the upcoming week

### Manual Trigger
- The workflow can also be triggered manually from the GitHub Actions UI with the `--force` flag to skip timezone checks

The system includes a timezone check to ensure it only processes registrations once per day during the 00:00-00:59 Amsterdam time window, accounting for potential GitHub Actions scheduling delays.