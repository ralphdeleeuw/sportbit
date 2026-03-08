# SportBit Auto Sign-Up for CrossFit Hilversum

## Project Description

This project automates the sign-up process for CrossFit WOD (Workout of the Day) classes at CrossFit Hilversum through the SportBit platform. It runs daily after midnight to register for predetermined weekly training slots, sends push notifications upon successful registration, and syncs events to Google Calendar.

The automation is designed for CrossFit members who want to secure their spots in popular classes without manually checking and signing up each time registration opens.

## Configuration

The following environment variables/secrets need to be configured:

### **SportBit Credentials**
- `SPORTBIT_USERNAME` — Your SportBit login username
- `SPORTBIT_PASSWORD` — Your SportBit login password

### **Google Calendar Integration**
- `GOOGLE_CREDENTIALS` — Google service account credentials JSON (either raw JSON string or file path)
- `CALENDAR_ID` — Google Calendar ID where events should be created (use "primary" for main calendar)

### **State Management**
- `GIST_ID` — GitHub Gist ID for storing signup state between runs
- `GIST_TOKEN` — GitHub personal access token with gist permissions

### **Push Notifications**
- `PUSHOVER_USER_KEY` — Your Pushover user key for receiving notifications
- `PUSHOVER_API_TOKEN` — Pushover application API token

### **Documentation Generation**
- `ANTHROPIC_API_KEY` — Anthropic API key for automatic README generation (used in update_readme workflow)

## Schedule

The auto sign-up workflow runs via GitHub Actions on the following schedule:

### **Automatic Runs**
- **Daily at 00:01 Amsterdam time** (accounts for both CET and CEST)
  - Winter time: `cron: "1 23 * * *"` (23:01 UTC)
  - Summer time: `cron: "1 22 * * *"` (22:01 UTC)

### **Weekly Training Schedule**
The script automatically signs up for these fixed weekly slots:
- **Monday** 20:00
- **Wednesday** 08:00
- **Thursday** 20:00
- **Saturday** 09:00

### **Manual Runs**
The workflow can also be triggered manually through the GitHub Actions UI using the "Run workflow" button.

### **How It Works**
1. The workflow runs shortly after midnight Amsterdam time
2. It checks for available classes in the next 8 days matching the weekly schedule
3. For each matching slot:
   - Skips if already signed up or manually cancelled
   - Attempts to register if spots are available
   - Joins waitlist if class is full
4. Sends push notifications for successful registrations
5. Creates Google Calendar events for confirmed spots
6. Stores state in GitHub Gist to track registrations and manual cancellations