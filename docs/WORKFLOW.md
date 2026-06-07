# Workflow Documentation

The system implements a human-in-the-loop review workflow where Devin-generated changes require human review before being considered complete.

## Session Lifecycle

### Workflow Diagram

```
Running
   │
   ▼
Needs Human Review
   │
   ├─ Completed (after review and approval)
   └─ Failed (if changes are rejected)
```

### Session States

1. **Running**: Devin is actively working on the remediation
2. **Needs Human Review**: Devin has completed remediation and opened a PR, awaiting human review
3. **Completed**: The PR has been reviewed, approved, and merged
4. **Failed**: The remediation failed or was rejected (can be recovered if PR is reopened)

### How It Works

1. When a Devin session is created, it's stored locally with status `running`
2. The system periodically polls the Devin API to check session status
3. When Devin completes work and opens a PR:
   - The local session record is updated to `needs_human_review`
   - GitHub labels are updated (removing `status:devin-running`, adding `status:devin-needs-human-review`)
   - A comment is added to the GitHub issue with PR link and validation summary
4. When the PR is reviewed and approved:
   - Call the completion endpoint to mark the session as `completed`
   - GitHub labels are updated (removing `status:devin-needs-human-review`, adding `status:devin-completed`)
5. If the PR is closed without merging (changes rejected):
   - The local session record is updated to `failed`
   - GitHub labels are updated (removing `status:devin-needs-human-review`, adding `status:devin-failed`)
   - A comment is added indicating the PR was rejected
6. If the PR is reopened after being closed:
   - The session status is reset from `failed` to `needs_human_review`
   - GitHub labels are updated (removing `status:devin-failed`, adding `status:devin-needs-human-review`)
   - A comment is added indicating the PR was reopened
7. If the remediation fails during execution:
   - The local session record is updated to `failed`
   - GitHub labels are updated (removing `status:devin-running`, adding `status:devin-failed`)
   - A comment is added with the failure reason

## Manual Sync

To manually trigger a sync pass over all running sessions:

```bash
curl -X POST http://localhost:8000/sessions/sync
```

This endpoint:
- Queries the Devin API for all running sessions
- Updates local session records based on actual Devin status
- Updates GitHub labels and comments for completed/failed sessions

## Automatic Sync

The `/metrics` endpoint automatically triggers a sync before returning metrics, ensuring the metrics reflect the latest session statuses.

## Why Polling?

This approach keeps the system simple:
- No need for webhook infrastructure from Devin
- No database or message queue required
- Local JSON store is sufficient for tracking
- Manual sync gives control over when to check status

The system is not hardcoded only for Superset or only for `risk:quality`. Superset is the first target repo, but the design is reusable for other repositories and other remediation labels.

## Human Review Workflow

### Automated PR Completion

The system supports automated completion when a pull request is merged:

1. When Devin completes remediation and opens a PR, the session status changes to `needs_human_review`
2. GitHub labels are updated to `status:devin-needs-human-review`
3. When you review and merge the PR:
   - GitHub sends a `pull_request` webhook with `action == "closed"` and `merged == true`
   - The system automatically finds the associated session by PR URL
   - Session status is updated to `completed`
   - GitHub labels are updated to `status:devin-completed`
   - A comment is added confirming completion

### PR Reopened Recovery

If a PR is closed without merging (marked as failed), it can be recovered:

1. When you reopen a closed PR:
   - GitHub sends a `pull_request` webhook with `action == "reopened"`
   - The system automatically finds the associated session by PR URL
   - Session status is reset from `failed` to `needs_human_review`
   - GitHub labels are updated (removing `status:devin-failed`, adding `status:devin-needs-human-review`)
   - A comment is added indicating the PR was reopened
2. When you then merge the reopened PR:
   - The system processes the merge event and marks the session as `completed`
   - GitHub labels are updated to `status:devin-completed`

### Webhook Configuration Summary

- Issue webhook: `https://your-domain.com/webhook/github/issue` (triggers remediation)
- PR webhook: `https://your-domain.com/webhook/github/pull_request` (auto-completes sessions)

### Manual Completion

If you prefer manual control, you can still use the completion endpoint after reviewing a PR:

```bash
curl -X POST http://localhost:8000/sessions/{session_id}/complete \
  -H "Content-Type: application/json" \
  -d '{
    "pull_request_url": "https://github.com/owner/repo/pull/123"
  }'
```

### View Review Queue

To view all sessions awaiting human review:

```bash
curl http://localhost:8000/sessions/review-queue
```

This returns all sessions with status `needs_human_review`.

### Mark Session as Completed

After reviewing and approving a PR, mark the session as completed:

```bash
curl -X POST http://localhost:8000/sessions/{session_id}/complete \
  -H "Content-Type: application/json" \
  -d '{
    "pull_request_url": "https://github.com/owner/repo/pull/123"
  }'
```

This will:
- Update session status to `completed`
- Remove `status:devin-needs-human-review` label
- Add `status:devin-completed` label
- Store the pull request URL and completion timestamp

### Mark Session as Needs Review (Manual)

If you need to manually mark a session as needing review:

```bash
curl -X POST http://localhost:8000/sessions/{session_id}/needs-review
```

This will:
- Update session status to `needs_human_review`
- Remove `status:devin-running` label
- Add `status:devin-needs-human-review` label
- Store the needs review timestamp
