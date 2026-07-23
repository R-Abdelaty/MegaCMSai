# MegaCMSai

## Chat API

Set `GUC_USERNAME`, `GUC_PASSWORD`, and the model provider API key in `.env`,
then start the backend:

```powershell
uvicorn api:app --reload --port 8000
```

The frontend sends `POST /api/gu-assistant/chat` (or the shorter alias
`POST /api/chat`):

```json
{
  "message":"english Show my current Signals grade.",
  "language":"english"
}
```

The response contains `reply` (Markdown formatted for the chatbot) and a
`session_id`. Save that ID and send it with every next message so the assistant
keeps the student's conversation context:

```json
{
  "message":"english What is my GPA?",
  "session_id":"the-returned-session-id",
  "language":"english"
}
```

### Language selector

Prefix every message with `english` or `franco`. GU replies in the selected
language; Franco means Egyptian Arabic written with English/Latin letters only,
with no Arabic script. Also send the current UI-toggle value as `language`
(`english` or `franco_egyptian`). The prefix and toggle must match; otherwise
GU returns a wrong-language message:

```json
{
  "message": "franco wariny daragat Math 3",
  "session_id": "the-returned-session-id",
  "language": "franco_egyptian"
}
```

Use `GET /api/health` for a health check. For deployment, set
`FRONTEND_ORIGINS` to a comma-separated list of permitted frontend origins.
