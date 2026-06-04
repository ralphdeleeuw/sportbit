# CrossFit Auto Sign-Up for Huppa

Automated sign-up system for CrossFit classes at CrossFit Hilversum using the Huppa platform. The system automatically registers you for predefined weekly workout slots, syncs with Google Calendar, and sends notifications about your registrations.

## Project Description

This project automates the process of signing up for CrossFit WOD (Workout of the Day) classes on a fixed weekly schedule. It runs daily via GitHub Actions to:

- Check for available classes matching your preferred schedule
- Automatically sign up for classes (or join the waitlist if full)
- Sync confirmed registrations to your Google Calendar
- Send push notifications about new registrations
- Track registration state to avoid duplicate sign-ups
- Detect manual cancellations and update calendar accordingly
- Send a weekly summary of upcoming classes every Sunday

The system is designed for members of CrossFit Hilversum who want to maintain a consistent training schedule without manually booking classes each week.

## Configuration

The following secrets must be configured in your GitHub repository settings:

### Huppa Credentials
- **`HUPPA_EMAIL`** — Your Huppa account email address
- **`HUPPA_PASSWORD`** — Your Huppa account password  
- **`HUPPA_SUBDOMAIN`** — The gym's subdomain (e.g., `crossfithilversum`)

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** — Google service account credentials JSON for calendar access
- **`CALENDAR_ID`** — Target Google Calendar ID (use `primary` for your main calendar)

### State Management
- **`GIST_ID`** — GitHub Gist ID for storing registration state between runs
- **`GIST_TOKEN`** — GitHub personal access token with gist permissions

### Push Notifications (Optional)
- **`PUSHOVER_USER_KEY`** — Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** — Pushover application API token
- **`VAPID_PRIVATE_KEY`** — VAPID private key for web push notifications
- **`VAPID_CLAIMS_EMAIL`** — Email address for VAPID claims

### Documentation Generation
- **`ANTHROPIC_API_KEY`** — Anthropic API key for automated README generation

## Schedule

The automation runs on two schedules via GitHub Actions:

### Daily Sign-Up Run
- **Time**: Every day at 00:01 UTC (01:01 CET / 02:01 CEST)
- **Purpose**: Checks for classes in the next 8 days and signs up for any matching the configured schedule
- **Current schedule**:
  - Monday 20:00
  - Wednesday 08:00
  - Thursday 20:00
  - Saturday 09:00
  - Sunday 09:00

### Weekly Summary
- **Time**: Sundays at 17:00 UTC (18:00 Amsterdam time)
- **Purpose**: Sends a push notification with an overview of all registered classes for the upcoming week

The workflow can also be triggered manually from the GitHub Actions tab for immediate sign-ups or testing.