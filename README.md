# SportBit Auto Sign-Up for CrossFit Hilversum

Automated sign-up system for CrossFit WOD classes at CrossFit Hilversum through the SportBit platform. The system automatically registers you for predefined weekly training slots, syncs confirmed registrations to Google Calendar, and sends push notifications via Pushover.

## Features

- **Automated Registration**: Automatically signs up for WOD classes based on a predefined weekly schedule
- **State Management**: Tracks registrations and manual cancellations using GitHub Gist storage
- **Google Calendar Sync**: Creates calendar events for successful registrations
- **Push Notifications**: Sends notifications via Pushover for successful registrations and weekly summaries
- **Manual Enrollment Detection**: Detects and syncs manually registered classes
- **Capacity Tracking**: Monitors class capacity for dashboard analytics

## Configuration

The following secrets must be configured in your GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`**: Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`**: Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`**: Google service account credentials in JSON format. This should be the full JSON content of your service account key file
- **`CALENDAR_ID`**: Google Calendar ID where events will be created (use `primary` for your main calendar, or a specific calendar ID like `abc123@group.calendar.google.com`)

### State Management
- **`GIST_ID`**: GitHub Gist ID for storing registration state between runs. Create a new private Gist and copy its ID from the URL
- **`GIST_TOKEN`**: GitHub personal access token with `gist` scope for reading/writing to the Gist

### Push Notifications
- **`PUSHOVER_USER_KEY`**: Your Pushover user key (found in your Pushover account settings)
- **`PUSHOVER_API_TOKEN`**: Pushover application API token (create an application in your Pushover account)

### Documentation Generation
- **`ANTHROPIC_API_KEY`**: Anthropic API key for automatic README generation (optional, only needed for documentation updates)

## Schedule

The automated workflow runs at the following times:

### Daily Registration Run
- **23:01 UTC** (00:01 Amsterdam winter time/CET)
- **22:01 UTC** (00:01 Amsterdam summer time/CEST)

The system automatically signs up for classes scheduled in the next 8 days according to the predefined weekly schedule:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

### Weekly Summary
- **Sundays at 17:00 UTC** (18:00 Amsterdam time)

Sends a push notification with an overview of all registrations for the upcoming week.

### Manual Runs
The workflow can also be triggered manually from the GitHub Actions UI. Manual runs skip the timezone check using the `--force` flag.

## How It Works

1. **Timezone Check**: The script only executes between 00:00-00:59 Amsterdam time to ensure it runs once daily
2. **Login**: Authenticates with SportBit using provided credentials
3. **Event Scanning**: Checks for available classes matching the predefined schedule
4. **Registration Logic**:
   - Skip if already registered or manually cancelled
   - Register for available slots (including waitlist)
   - Update state in GitHub Gist
   - Create Google Calendar event
   - Send push notification
5. **Manual Enrollment Detection**: Scans for manually registered classes and syncs them to the calendar
6. **State Persistence**: Updates the GitHub Gist with current registration state and capacity data