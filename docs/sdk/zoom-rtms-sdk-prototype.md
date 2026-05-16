# Zoom RTMS SDK Prototype

This prototype keeps the SDK product separate from the AI Interviewer app code.
The SDK package lives in `sdk/` and exposes FastAPI routes under
`/api/v1/sdk/*` and `/api/v1/zoom/*`.

## Local Configuration

Use SQLite locally unless you intentionally want to point the SDK at Postgres.

```env
SDK_DB_TYPE=sqlite
SDK_SQLITE_PATH=.sdk/sdk.sqlite

ZOOM_CLIENT_ID=your_zoom_rtms_client_id
ZOOM_CLIENT_SECRET=your_zoom_rtms_client_secret
ZOOM_WEBHOOK_SECRET_TOKEN=your_zoom_webhook_secret_token
ZOOM_OAUTH_REDIRECT_URL=https://<tunnel>/api/v1/zoom/oauth/callback
ZOOM_RTMS_WEBHOOK_URL=https://<tunnel>/api/v1/zoom/rtms/webhook
ZOOM_DEFAULT_WAKE_WORDS="MeetMind,Hey MeetMind"
```

For staging, either set `SDK_DATABASE_URL` directly or set:

```env
SDK_DB_TYPE=postgresql
SDK_DB_HOST=...
SDK_DB_PORT=5432
SDK_DB_USER=...
SDK_DB_PASSWORD=...
SDK_DB_NAME=sdk
```

## Zoom App Setup

1. Create a Zoom RTMS app.
2. Enable the RTMS started and stopped webhook events.
3. Configure the webhook endpoint as `ZOOM_RTMS_WEBHOOK_URL`.
4. Configure OAuth redirect as `ZOOM_OAUTH_REDIRECT_URL`.
5. Enable the required RTMS scopes for meeting audio and transcript access.

## Prototype Flow

1. Create an SDK session:

   ```http
   POST /api/v1/sdk/sessions
   {
     "platform": "zoom",
     "meeting_id": "123456789",
     "meeting_url": "https://zoom.us/j/123456789",
     "agent_name": "MeetMind",
     "wake_words": ["MeetMind", "Hey MeetMind"]
   }
   ```

2. Start a real Zoom meeting configured for the RTMS app.
3. Zoom sends `meeting.rtms_started` to `/api/v1/zoom/rtms/webhook`.
4. The SDK starts a real `rtms.Client`, joins the RTMS stream, and persists transcript turns.
5. Read transcript turns:

   ```http
   GET /api/v1/sdk/sessions/{session_id}/transcript
   ```

## Current Scope

v0.1 proves Zoom join/listen/transcript persistence through RTMS. Runtime RTMS is real; tests only simulate webhook payload parsing and database behavior.

v0.2 speaking is intentionally represented as a bridge interface. Zoom RTMS receives media; speaking back into a Zoom call requires a Meeting SDK bridge, which should be implemented separately without coupling it to transcript ingestion.
