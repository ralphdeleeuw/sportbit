# SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for CrossFit WOD classes at CrossFit Hilversum on a weekly schedule. The system runs daily after midnight Amsterdam time, checks for available classes according to a predefined schedule, and registers for them. It includes Google Calendar synchronization, push notifications, and tracks state to handle manual cancellations.

## Project Description

This project automates the sign-up process for CrossFit classes at CrossFit Hilversum through the SportBit platform. It's designed for members who want to ensure they're registered for their regular training slots without having to manually sign up each time.

### Key Features

- **Automated Sign-ups**: Registers for classes based on a predefined weekly schedule
- **State Management**: Tracks signed-up and manually cancelled classes via GitHub Gist
- **Google Calendar Sync**: Automatically adds confirmed classes to your Google Calendar
- **Push Notifications**: Sends notifications via Pushover when successfully registered
- **Manual Cancellation Detection**: Respects manual cancellations and won't re-register
- **Weekly Summary**: Sends a weekly overview of all upcoming registrations every Sunday
- **Capacity Tracking**: Monitors and stores class capacity data for dashboard analytics

### Target Schedule

The system is configured to sign up for classes at these times:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

## Configuration

All configuration is done through environment variables (GitHub Secrets when running in GitHub Actions):

### Required Secrets

- **`SPORTBIT_USERNAME`**: Your SportBit login username
- **`SPORTBIT_PASSWORD`**: Your SportBit login password

### State Management

- **`GIST_ID`**: GitHub Gist ID for storing registration state between runs
- **`GIST_TOKEN`**: GitHub personal access token with gist scope for updating the state

### Google Calendar Integration

- **`GOOGLE_CREDENTIALS`**: Google service account credentials in JSON format for calendar access
- **`CALENDAR_ID`**: Google Calendar ID where events should be created (use "primary" for main calendar)

### Push Notifications

- **`PUSHOVER_USER_KEY`**: Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`**: Pushover application API token

### README Generation

- **`ANTHROPIC_API_KEY`**: Anthropic API key for automatic README generation (used in update workflow)

## Schedule

The automation runs on the following schedule:

### Daily Sign-up Runs

- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

The system runs just after midnight Amsterdam time every day, automatically adjusting for daylight saving time. It looks ahead 8 days and registers for any scheduled classes that match the predefined weekly schedule.

### Weekly Summary

- **Every Sunday at 17:00 UTC** (18:00 Amsterdam time)

Sends a push notification with an overview of all registered classes for the upcoming week.

### Manual Trigger

The workflow can also be triggered manually from the GitHub Actions UI. When triggered manually, the `--force` flag is automatically added to skip the timezone check, allowing you to run the sign-up process at any time.

### How It Works

1. The workflow runs daily at 00:01 Amsterdam time
2. It checks for classes in the next 8 days that match the predefined schedule
3. For each matching class:
   - Checks if already registered or manually cancelled
   - If not, attempts to register
   - On success: updates state, sends notification, creates calendar event
4. Detects manual enrollments and cancellations to keep state synchronized
5. Stores capacity data for analytics

The system respects manual actions - if you cancel a class manually, it won't attempt to re-register you for that specific instance.