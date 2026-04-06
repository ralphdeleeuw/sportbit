# CrossFit Hilversum Auto Sign-Up

Automatically signs up for CrossFit WOD classes at CrossFit Hilversum through the SportBit platform. The system runs daily after midnight Amsterdam time, checks for scheduled classes within the next 8 days, and automatically registers you. It also syncs confirmed registrations to Google Calendar and sends push notifications via Pushover.

## Features

- **Automated sign-up** for pre-configured weekly schedule
- **Google Calendar sync** for confirmed registrations
- **Push notifications** via Pushover for successful sign-ups
- **Weekly summary** sent every Sunday evening
- **State management** using GitHub Gist to track sign-ups and manual cancellations
- **Manual enrollment detection** for classes outside the regular schedule
- **Timezone-aware** scheduling (Amsterdam time, handles DST automatically)

## Configuration

The following secrets need to be configured in your GitHub repository settings:

### SportBit Credentials
- **`SPORTBIT_USERNAME`** - Your SportBit login username
- **`SPORTBIT_PASSWORD`** - Your SportBit login password

### Google Calendar Integration
- **`GOOGLE_CREDENTIALS`** - Google Service Account credentials JSON (raw JSON content, not a file path)
- **`CALENDAR_ID`** - Google Calendar ID where events will be created (use `primary` for your main calendar)

### State Management
- **`GIST_ID`** - GitHub Gist ID for storing persistent state between runs
- **`GIST_TOKEN`** - GitHub Personal Access Token with `gist` scope for updating the state Gist

### Push Notifications
- **`PUSHOVER_USER_KEY`** - Your Pushover user key
- **`PUSHOVER_API_TOKEN`** - Pushover API token for your application

### Documentation Generation
- **`ANTHROPIC_API_KEY`** - Anthropic API key for automatic README generation (optional)

## Schedule

The workflow runs on the following schedule:

1. **Daily at 00:01 Amsterdam time** - Main auto sign-up process
   - Winter time (CET): `23:01 UTC`
   - Summer time (CEST): `22:01 UTC`
   - Both cron schedules are configured to handle daylight saving time transitions

2. **Sunday at 18:00 Amsterdam time** - Weekly summary notification
   - Sends an overview of all upcoming registrations for the week

3. **Manual trigger** - Can be run manually from GitHub Actions UI
   - Uses `--force` flag to skip timezone check for immediate execution

The default schedule attempts to register for:
- Monday 20:00
- Wednesday 08:00
- Thursday 20:00
- Saturday 09:00
- Sunday 09:00

The system looks ahead 8 days by default, allowing registration as soon as slots become available on SportBit.