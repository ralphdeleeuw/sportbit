# SportBit Auto Sign-Up for CrossFit Hilversum

Automated sign-up system for CrossFit classes at CrossFit Hilversum using the SportBit platform. The system automatically registers for predefined weekly training sessions and syncs them to Google Calendar.

## Project Description

This project automates the process of signing up for CrossFit WOD (Workout of the Day) classes through the SportBit platform. It's designed for members of CrossFit Hilversum who want to secure their spots in popular classes without manually checking and registering each time.

### Key Features

- **Automatic sign-up** for predefined weekly training schedule
- **State management** to track signed-up classes and prevent re-registration of manually cancelled sessions
- **Google Calendar integration** to automatically create calendar events for successful registrations
- **Push notifications** via Pushover when successfully signed up
- **Dry-run mode** for testing without making actual bookings
- **GitHub Actions automation** for daily execution

## Configuration

The following environment variables/secrets need to be configured:

### SportBit Authentication
- **`SPORTBIT_USERNAME`** - Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`** - Your SportBit account password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** - Google service account credentials JSON (entire JSON content as a string). This should be a service account with Calendar API access
- **`CALENDAR_ID`** - Target Google Calendar ID where events will be created (use "primary" for your main calendar)

### State Management
- **`GIST_ID`** - GitHub Gist ID for storing state between runs (tracks signed-up and manually cancelled classes)
- **`GIST_TOKEN`** - GitHub Personal Access Token with gist scope for reading/writing the state file

### Push Notifications
- **`PUSHOVER_USER_KEY`** - Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`** - Pushover application API token

### README Generation
- **`ANTHROPIC_API_KEY`** - Anthropic API key for automatic README generation (used in the update_readme workflow)

## Schedule

The auto sign-up workflow runs daily via GitHub Actions at:
- **00:01 CET** (Amsterdam winter time) - via cron `1 23 * * *`
- **00:01 CEST** (Amsterdam summer time) - via cron `1 22 * * *`

The script looks ahead 8 days and attempts to register for the following weekly schedule:
- **Monday 20:00**
- **Wednesday 08:00**
- **Thursday 20:00**
- **Saturday 09:00**

### How it Works

1. The workflow triggers automatically every night at 00:01 Amsterdam time
2. The script logs into SportBit using provided credentials
3. It checks for available classes matching the predefined schedule in the next 8 days
4. For each matching class:
   - Skip if already registered or manually cancelled
   - Attempt to sign up (including waitlist if class is full)
   - Create a Google Calendar event on success
   - Send a push notification via Pushover
5. State is persisted to a GitHub Gist to track registrations and manual cancellations

The workflow can also be triggered manually from the GitHub Actions tab for immediate execution.