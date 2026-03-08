# SportBit Auto Sign-Up for CrossFit Hilversum

Automated sign-up system for CrossFit WOD classes at CrossFit Hilversum using the SportBit platform. The system automatically registers for predefined weekly training slots and syncs successful registrations to Google Calendar.

## Project Description

This project automates the registration process for CrossFit classes at CrossFit Hilversum through the SportBit platform. It runs daily just after midnight (Amsterdam time) and attempts to sign up for classes according to a predefined weekly schedule. The system maintains state to track which classes have been signed up for and respects manual cancellations made through the SportBit platform.

### Key Features
- Automatic daily sign-ups for CrossFit WOD classes
- Google Calendar integration for confirmed registrations
- Push notifications via Pushover
- State management to prevent duplicate sign-ups
- Respects manual cancellations
- Dry-run mode for testing

### Target Audience
CrossFit Hilversum members who want to automate their weekly class registrations and maintain a consistent training schedule.

## Configuration

The following environment variables must be configured as GitHub Secrets:

### SportBit Credentials
- **`SPORTBIT_USERNAME`**: Your SportBit login username (email address)
- **`SPORTBIT_PASSWORD`**: Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`**: Google service account credentials in JSON format. This should be the complete JSON content of a service account key file with Calendar API access
- **`CALENDAR_ID`**: Google Calendar ID where events should be created (use "primary" for your main calendar or a specific calendar ID)

### State Management
- **`GIST_ID`**: GitHub Gist ID for storing registration state between runs. Create an empty private Gist and use its ID
- **`GIST_TOKEN`**: GitHub personal access token with `gist` scope for reading/writing to the state Gist

### Push Notifications
- **`PUSHOVER_USER_KEY`**: Your Pushover user key for receiving notifications
- **`PUSHOVER_API_TOKEN`**: Pushover application API token

### Documentation Generation
- **`ANTHROPIC_API_KEY`**: Claude API key for automatic README generation (optional, only needed for the update_readme workflow)

## Schedule

The automated sign-up system runs on the following schedule:

### Weekly Training Schedule
The system is configured to sign up for these weekly slots:
- **Monday**: 20:00
- **Wednesday**: 08:00
- **Thursday**: 20:00
- **Saturday**: 09:00

### GitHub Actions Schedule
The workflow runs daily at two different times to account for daylight saving time:
- **23:01 UTC** (00:01 Amsterdam winter time - CET)
- **22:01 UTC** (00:01 Amsterdam summer time - CEST)

The script includes a timezone check to ensure it only executes once per day between 00:00 and 00:30 Amsterdam time, regardless of which cron trigger activated it.

### How It Works
1. Every night just after midnight (Amsterdam time), the workflow triggers
2. The script logs into SportBit and checks for classes in the next 8 days
3. For each scheduled slot, it attempts to register if not already signed up
4. Successful registrations are:
   - Recorded in the GitHub Gist state file
   - Added to your Google Calendar
   - Notified via Pushover
5. The system respects manual cancellations - if you cancel a class through SportBit, the script won't re-register you for that specific class

### Manual Execution
The workflow can also be triggered manually through the GitHub Actions interface using the "Run workflow" button. When running manually, use the `--force` flag to bypass the timezone check.