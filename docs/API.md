# API Documentation

The system provides REST API endpoints for webhooks, simulation, and metrics.

## Endpoints

### GET /dashboard
Operational dashboard for engineering leadership visibility.

### POST /webhook/github/issue
Accept GitHub issue webhook payloads (only triggers on `action == "labeled"`).

### POST /webhook/github/pull_request
Accept GitHub pull request webhook payloads (automatically completes sessions when PR is merged).

### POST /simulate
Simulate remediation events without live webhooks.

### GET /sessions
View all tracked Devin sessions.

### GET /sessions/review-queue
View all sessions awaiting human review.

### POST /sessions/{session_id}/needs-review
Mark a session as needing human review.

### POST /sessions/{session_id}/complete
Mark a session as completed (after review).

### POST /sessions/sync
Manually trigger a sync pass over all running Devin sessions.

### GET /metrics
View operational metrics (automatically syncs sessions before returning).

### GET /health
Health check endpoint.

### GET /health/devin
Test Devin API authentication without creating a session.

## Example Usage

### Simulate an Event

```bash
curl -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "emillaurence",
    "repo": "superset",
    "number": 1,
    "title": "Test issue",
    "body": "Test description",
    "labels": ["devin-remediate", "risk:quality"],
    "url": "https://github.com/emillaurence/superset/issues/1"
  }'
```

### View All Sessions

```bash
curl http://localhost:8000/sessions
```

### View Metrics

```bash
curl http://localhost:8000/metrics
```

### Manual Sync

```bash
curl -X POST http://localhost:8000/sessions/sync
```

### Test Devin Authentication

```bash
curl http://localhost:8000/health/devin
```

Expected response:
```json
{
  "status": "authenticated",
  "principal_type": "service user",
  "service_user_name": "your-service-user",
  "org_id": "your-org-id"
}
```
