# AI Chat Query Assistant — API Contract

## Base Path

```
/api/v1/interviews/{interview_id}
```

All endpoints require authentication via `access_token` cookie or `Authorization: Bearer <token>` header.

---

## 1. Send Text Query

Send a natural-language text question about a candidate's interview performance.

```
POST /api/v1/interviews/{interview_id}/chat
```

### Request

```json
{
  "query": "Did the candidate demonstrate leadership skills?"
}
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Query answered",
  "data": {
    "role": "assistant",
    "content": "Yes, the candidate mentioned leading a team of 5 engineers on the payment infrastructure project. They described resolving a production incident by coordinating across three teams, which demonstrates leadership under pressure.",
    "sent_at": "2026-06-06T08:52:48Z",
    "sequence_no": 3
  }
}
```

### Error `400 Bad Request`

```json
{
  "success": false,
  "message": "query must have at least 1 character",
  "error": {
    "code": "validation_error",
    "details": null
  }
}
```

---

## 2. Send Voice Query

Upload an audio file containing a spoken question about the interview.

```
POST /api/v1/interviews/{interview_id}/chat/voice
```

### Request

`Content-Type: multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | `UploadFile` | Audio file. Supported formats: `webm`, `wav`, `mp3`, `m4a`, `ogg`, `flac`. Max size: **25 MB**. |

### Response `200 OK`

```json
{
  "success": true,
  "message": "Voice query answered",
  "data": {
    "role": "assistant",
    "content": "The candidate scored 4/5 on technical problem-solving. They effectively debugged the database deadlock scenario and provided an optimized query as a follow-up.",
    "transcription": "How did the candidate perform on technical problem solving?",
    "sent_at": "2026-06-06T08:53:12Z",
    "sequence_no": 5
  }
}
```

### Error `400 Bad Request` — Unsupported format

```json
{
  "success": false,
  "message": "Unsupported audio format: audio/mp2",
  "error": {
    "code": "unsupported_audio_format",
    "details": null
  }
}
```

### Error `413 Payload Too Large`

```json
{
  "success": false,
  "message": "Audio file too large (max 25 MB)",
  "error": {
    "code": "file_too_large",
    "details": null
  }
}
```

---

## 3. Send Document Query

Upload a document (PDF, DOCX, or TXT) whose content will be used as the question context. Useful when a recruiter wants to ask a question based on notes in a file.

```
POST /api/v1/interviews/{interview_id}/chat/document
```

### Request

`Content-Type: multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | `UploadFile` | Document file. Supported formats: `.pdf`, `.docx`, `.txt`. Max size: **10 MB**. |

### Response `200 OK`

```json
{
  "success": true,
  "message": "Document query answered",
  "data": {
    "role": "assistant",
    "content": "Based on the comparison document, the candidate's experience with React and Node.js aligns well with the role requirements. Their 4 years of full-stack development matches the seniority level requested.",
    "document_text_preview": "Candidate Comparison\n\nName: John Doe\nPosition: Senior Full-Stack Developer\nExperience: 4 years\nSkills: React, Node.js, PostgreSQL, Docker\n\nNotes: Strong system design communication skills...",
    "sent_at": "2026-06-06T08:54:01Z",
    "sequence_no": 7
  }
}
```

### Error `400 Bad Request` — Unsupported format

```json
{
  "success": false,
  "message": "Unsupported document format: .xlsx",
  "error": {
    "code": "unsupported_document_format",
    "details": null
  }
}
```

### Error `413 Payload Too Large`

```json
{
  "success": false,
  "message": "Document file too large (max 10 MB)",
  "error": {
    "code": "file_too_large",
    "details": null
  }
}
```

---

## 4. Get Chat History

Retrieve all recruiter Q&A messages for an interview, ordered chronologically.

```
GET /api/v1/interviews/{interview_id}/chat
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Chat history retrieved successfully",
  "data": {
    "interview_id": "a1b2c3d4-...",
    "total_messages": 6,
    "messages": [
      {
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "role": "user",
        "content": "How did the candidate handle the system design question?",
        "sent_at": "2026-06-06T08:50:00Z",
        "sequence_no": 1
      },
      {
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d480",
        "role": "assistant",
        "content": "The candidate proposed a microservices architecture with proper load balancing...",
        "sent_at": "2026-06-06T08:50:02Z",
        "sequence_no": 2
      },
      {
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d481",
        "role": "user",
        "content": "Did the candidate demonstrate leadership skills?",
        "sent_at": "2026-06-06T08:51:00Z",
        "sequence_no": 3
      },
      {
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d482",
        "role": "assistant",
        "content": "Yes, the candidate mentioned leading a team of 5 engineers...",
        "sent_at": "2026-06-06T08:51:02Z",
        "sequence_no": 4
      }
    ]
  }
}
```

### Response — Empty history (no messages yet)

```json
{
  "success": true,
  "message": "Chat history retrieved successfully",
  "data": {
    "interview_id": "a1b2c3d4-...",
    "total_messages": 0,
    "messages": []
  }
}
```

---

## Error Envelope (all endpoints)

All errors follow the same standard envelope:

```json
{
  "success": false,
  "message": "Human-readable error description",
  "error": {
    "code": "machine_readable_code",
    "details": null
  }
}
```

### Common error codes

| HTTP Status | Code | Meaning |
|---|---|---|
| 401 | `unauthorized` | Missing or expired token |
| 403 | `email_not_verified` | User email not verified |
| 404 | `interview_not_found` | Interview doesn't exist or not owned by user |
| 400 | `unsupported_audio_format` | Audio MIME type not in allowed list |
| 400 | `unsupported_document_format` | File extension not in `.pdf`, `.docx`, `.txt` |
| 413 | `file_too_large` | Exceeds size limit |
| 400 | `invalid_file` | Document parsing failed (corrupted or unreadable) |
| 400 | `validation_error` | Request body validation failure |

---

## Data Model — `ChatMessageResponse`

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` | Message unique identifier |
| `role` | `string` | `"user"` for recruiter queries, `"assistant"` for AI answers |
| `content` | `string` | Message text content |
| `sent_at` | `ISO 8601 datetime` | Timestamp of when the message was created |
| `sequence_no` | `integer` | Monotonically increasing sequence within the interview |

---

## Notes for Frontend

- **Polling strategy**: Use `GET /chat` to fetch history. There is no WebSocket for real-time chat — the `POST` endpoints return the answer directly in the response.
- **Audio formats**: Accept `webm`, `wav`, `mp3`, `m4a`, `ogg`, `flac`. Record using the browser's `MediaRecorder` API with `audio/webm` codec for best compatibility.
- **Document formats**: Only `.pdf`, `.docx`, `.txt`. Show a clear error if the user tries to upload unsupported files.
- **Layout responsive**: The API returns raw data; layout responsiveness is a frontend concern.
- **Ambiguity**: The AI will attempt to resolve vague questions based on closest meaning. If no connection can be made, it will say the info isn't available — display this gracefully.
