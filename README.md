# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically sign up for CrossFit WOD classes at CrossFit Hilversum using the SportBit platform. This GitHub Actions workflow runs daily to register you for your preferred training schedule, syncs with Google Calendar, and sends push notifications about successful registrations.

## Features

- **Automated registration** for CrossFit classes based on your weekly schedule
- **Google Calendar integration** to add registered classes to your calendar
- **State management** using GitHub Gist to track registrations and manual cancellations
- **Push notifications** for successful sign-ups and weekly summaries
- **Waitlist support** when classes are full
- **Manual cancellation detection** to avoid re-registering for cancelled classes

## Configuration

All configuration is done through GitHub repository secrets. Set these up in your repository under Settings → Secrets and variables → Actions:

### Required Secrets

- **`SPORTBIT_USERNAME`** - Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** - Your SportBit login password

### Google Calendar Integration (Optional)

- **`GOOGLE_CREDENTIALS`** - Google service account credentials JSON. Create a service account in Google Cloud Console and paste the entire JSON key here
- **`CALENDAR_ID`** - Google Calendar ID where events should be created (use `primary` for your main calendar, or a specific calendar ID like `abc123@group.calendar.google.com`)

### State Management (Required)

- **`GIST_ID`** - GitHub Gist ID for storing registration state. Create a new secret gist and copy its ID from the URL
- **`GIST_TOKEN`** - GitHub personal access token with `gist` scope. Generate at Settings → Developer settings → Personal access tokens

### Push Notifications (Optional)

- **`PUSHOVER_USER_KEY`** - Your Pushover user key for receiving push notifications
- **`PUSHOVER_API_TOKEN`** - Pushover application API token

### README Generation (Optional)

- **`ANTHROPIC_API_KEY`** - Anthropic Claude API key for automatic README generation

## Schedule

The workflow runs automatically on two schedules:

1. **Daily at 00:01 UTC** (01:01 CET / 02:01 CEST) - Checks for upcoming classes in the next 8 days and registers for scheduled slots
2. **Sundays at 17:00 UTC** (18:00 Amsterdam time) - Sends a weekly summary of all upcoming registrations via push notification

The default training schedule is configured for:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

You can also manually trigger the workflow from the GitHub Actions tab to run sign-ups immediately.

## How It Works

1. The workflow logs into SportBit using your credentials
2. Scans the next 8 days for your scheduled training slots
3. Registers for any classes you're not already signed up for
4. Creates Google Calendar events for successful registrations
5. Tracks all registrations in a GitHub Gist to:
   - Avoid duplicate registrations
   - Detect manual cancellations (won't re-register cancelled classes)
   - Remember manually enrolled classes
6. Sends push notifications for new registrations
7. On Sundays, sends a weekly overview of all upcoming classes

The system respects manual changes - if you cancel a class or sign up for additional sessions manually, it will detect and honor these modifications.