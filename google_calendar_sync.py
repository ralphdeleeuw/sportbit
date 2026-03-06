import os
import sys
import json
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Define the scopes required for Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']

class GoogleCalendarSync:
    def __init__(self, creds_json=None, token_json='token.json'):
        self.creds = self.get_credentials(creds_json, token_json)
        self.service = build('calendar', 'v3', credentials=self.creds)

    def get_credentials(self, creds_json, token_json):
        if creds_json:
            # Check if it's a raw JSON string or a file path
            if creds_json.strip().startswith('{'):
                # It's raw JSON content (e.g. from an environment variable)
                creds_info = json.loads(creds_json)
                credentials = service_account.Credentials.from_service_account_info(
                    creds_info, scopes=SCOPES)
            else:
                # It's a file path
                credentials = service_account.Credentials.from_service_account_file(
                    creds_json, scopes=SCOPES)
        else:
            # If using OAuth2 flow
            flow = InstalledAppFlow.from_client_secrets_file(token_json, SCOPES)
            credentials = flow.run_local_server(port=0)
        return credentials

    def list_events(self, calendar_id='primary'):
        events_result = self.service.events().list(
            calendarId=calendar_id, maxResults=10,
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        return events

    def create_event(self, calendar_id='primary', event_details=None):
        if event_details is None:
            raise ValueError('Event details must be provided.')
        event = self.service.events().insert(
            calendarId=calendar_id, body=event_details
        ).execute()
        return event

if __name__ == '__main__':
    creds_file = None
    if len(sys.argv) > 1:
        creds_file = sys.argv[1]  # Can be a file path OR raw JSON string
    sync = GoogleCalendarSync(creds_json=creds_file)
    events = sync.list_events()
    for event in events:
        print(event['summary'], event['start'])
