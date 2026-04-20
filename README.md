# SportBit CrossFit Auto Sign-Up

Automated sign-up system for CrossFit Hilversum classes through the SportBit platform. The system automatically registers for predefined weekly training slots, syncs with Google Calendar, and sends push notifications.

## Project Description

This project automates the registration process for CrossFit WOD (Workout of the Day) classes at CrossFit Hilversum. It runs daily via GitHub Actions, checking for available slots according to a predefined schedule and automatically signing up when spots are available. The system maintains state tracking to handle manual cancellations and includes Google Calendar integration for seamless schedule management.

Key features:
- Automatic daily sign-ups for predefined training slots
- Google Calendar synchronization
- Push notifications via Pushover
- State management for tracking registrations and cancellations
- Weekly schedule summary notifications
- Support for waitlist detection

## Configuration

The following secrets must be configured in your GitHub repository settings:

### SportBit Credentials
- **SPORTBIT_USERNAME** — Your SportBit login username
- **SPORTBIT_PASSWORD** — Your SportBit login password

### Google Calendar Integration
- **GOOGLE_CREDENTIALS** — Google service account credentials JSON (for calendar synchronization)
- **CALENDAR_ID** — Target Google Calendar ID where events will be created (use "primary" for main calendar)

### State Management
- **GIST_ID** — GitHub Gist ID for storing registration state between runs
- **GIST_TOKEN** — GitHub personal access token with gist permissions

### Push Notifications
- **PUSHOVER_USER_KEY** — Your Pushover user key for receiving notifications
- **PUSHOVER_API_TOKEN** — Pushover API token for your application

### README Generation
- **ANTHROPIC_API_KEY** — Claude API key for automatic README generation (optional)

## Schedule

The automation runs on the following schedule:

### Daily Sign-Up Runs
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

These runs execute just after midnight Amsterdam time to sign up for classes in the coming week. The system automatically detects the current timezone (CET/CEST) and only executes during the appropriate schedule.

### Weekly Summary
- **Sundays at 17:00 UTC** (18:00 Amsterdam time)

Sends a push notification with an overview of all registered classes for the upcoming week.

### Training Schedule
The system automatically signs up for the following weekly slots:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

The workflow can also be triggered manually through the GitHub Actions interface, which includes a `--force` flag to bypass timezone checks for testing purposes.