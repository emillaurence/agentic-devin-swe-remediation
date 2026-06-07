# Agentic Devin SWE Remediation

An event-driven remediation platform that helps engineering teams move from reactive issue management to an agentic operating model.

## Problem Context

Large engineering teams already have many signals from GitHub issues, dependency scans, static analysis, failing tests, and operational alerts. The problem is that these signals often stop at detection. Humans still need to triage, understand the codebase, apply fixes, validate changes, and open pull requests.

This system closes that gap by using Devin as an autonomous software engineering worker.

Traditional automation tells teams what is broken. Devin helps complete the engineering work.

## Architecture

The system is built as a Python FastAPI application with the following components:

- **FastAPI Application** (`app/main.py`): REST API endpoints for webhooks, simulation, and metrics
- **Devin Client** (`app/devin_client.py`): Integration with the Devin API for creating autonomous sessions
- **GitHub Client** (`app/github_client.py`): Integration with GitHub API for issue comments and label management
- **Session Store** (`app/store.py`): Local JSON-based storage for tracking Devin sessions
- **Data Models** (`app/models.py`): Pydantic models for issues, sessions, and metrics

### API Endpoints

- `GET /dashboard` - Operational dashboard for engineering leadership visibility
- `POST /webhook/github/issue` - Accept GitHub issue webhook payloads (only triggers on `action == "labeled"`)
- `POST /webhook/github/pull_request` - Accept GitHub pull request webhook payloads (automatically completes sessions when PR is merged)
- `POST /simulate` - Simulate remediation events without live webhooks
- `GET /sessions` - View all tracked Devin sessions
- `GET /sessions/review-queue` - View all sessions awaiting human review
- `POST /sessions/{session_id}/needs-review` - Mark a session as needing human review
- `POST /sessions/{session_id}/complete` - Mark a session as completed (after review)
- `POST /sessions/sync` - Manually trigger a sync pass over all running Devin sessions
- `GET /metrics` - View operational metrics (automatically syncs sessions before returning)
- `GET /health` - Health check endpoint

## Label-Driven Operating Model

The system is generic and label-driven. It uses GitHub labels to control behavior:

### Trigger Label

- `devin-remediate` - Triggers the Devin remediation workflow when added to an issue

### Risk/Category Labels

- `risk:security` - Indicates a security-focused remediation (dependencies, vulnerabilities, security fixes)
- `risk:quality` - Indicates a quality-focused remediation (code quality, maintainability, linting, static analysis)

### Status Labels

- `status:devin-running` - Automatically added when a Devin session starts
- `status:devin-needs-human-review` - Added when Devin completes remediation and opens a PR, awaiting human review
- `status:devin-completed` - Added when remediation is reviewed and approved
- `status:devin-failed` - Added when remediation fails

## Session Lifecycle

The system implements a human-in-the-loop review workflow where Devin-generated changes require human review before being considered complete.

### Workflow

```
Running
   │
   ▼
Needs Human Review
   │
   ├─ Completed (after review and approval)
   ├─ Failed (if changes are rejected)
   └─ Running (if changes are requested)
```

### Session States

1. **Running**: Devin is actively working on the remediation
2. **Needs Human Review**: Devin has completed remediation and opened a PR, awaiting human review
3. **Completed**: The PR has been reviewed, approved, and merged
4. **Failed**: The remediation failed or was rejected

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
5. If the remediation fails:
   - The local session record is updated to `failed`
   - GitHub labels are updated (removing `status:devin-running`, adding `status:devin-failed`)
   - A comment is added with the failure reason

### Manual Sync

To manually trigger a sync pass over all running sessions:

```bash
curl -X POST http://localhost:8000/sessions/sync
```

This endpoint:
- Queries the Devin API for all running sessions
- Updates local session records based on actual Devin status
- Updates GitHub labels and comments for completed/failed sessions

### Automatic Sync

The `/metrics` endpoint automatically triggers a sync before returning metrics, ensuring the metrics reflect the latest session statuses.

### Why Polling?

This approach keeps the system simple:
- No need for webhook infrastructure from Devin
- No database or message queue required
- Local JSON store is sufficient for tracking
- Manual sync gives control over when to check status

The system is not hardcoded only for Superset or only for `risk:quality`. Superset is the first target repo, but the design is reusable for other repositories and other remediation labels.

## Setup Instructions

### Prerequisites

- Python 3.11 or higher
- Devin API key
- GitHub personal access token with repo permissions

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

Required environment variables:

- `DEVIN_API_KEY` - Your Devin API key
- `DEVIN_ORG_ID` - Your Devin organization ID
- `GITHUB_TOKEN` - GitHub personal access token with repo permissions

Optional environment variables (with defaults):

- `DEFAULT_GITHUB_OWNER=emillaurence` - Default repository owner
- `DEFAULT_GITHUB_REPO=superset` - Default repository name
- `TRIGGER_LABEL=devin-remediate` - Label that triggers remediation
- `STATUS_RUNNING_LABEL=status:devin-running` - Label for running sessions
- `STATUS_NEEDS_REVIEW_LABEL=status:devin-needs-human-review` - Label for sessions needing human review
- `STATUS_COMPLETED_LABEL=status:devin-completed` - Label for completed sessions
- `STATUS_FAILED_LABEL=status:devin-failed` - Label for failed sessions
- `STORE_PATH=./data/sessions.json` - Path to session storage file

### Local Development

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set up environment variables:

```bash
export DEVIN_API_KEY=your_devin_api_key
export DEVIN_ORG_ID=your_devin_org_id
export GITHUB_TOKEN=your_github_token
```

3. Run the application:

```bash
python -m app.main
```

The API will be available at `http://localhost:8000`

### Using ngrok for Local Webhook Testing

To test GitHub webhooks locally without deploying, use ngrok to expose your local server:

1. Install ngrok (if not already installed):
   - macOS: `brew install ngrok`
   - Or download from https://ngrok.com

2. Start ngrok to tunnel port 8000:
   ```bash
   ngrok http 8000
   ```

3. Copy the ngrok URL (e.g., `https://abc123.ngrok.io`)

4. Configure your GitHub webhook to point to:
   ```
   https://abc123.ngrok.io/webhook/github/issue
   ```

5. Select "Issues" as the event type

6. Optionally add a webhook secret for security (add `GITHUB_WEBHOOK_SECRET` to your `.env` file)

Note: The ngrok URL changes each time you restart ngrok, so you'll need to update your GitHub webhook configuration accordingly.

### Testing Devin Authentication

To verify your Devin API credentials are configured correctly without creating a session:

```bash
curl http://localhost:8000/health/devin
```

This endpoint checks authentication only and does not create a Devin session. It returns:
- `status`: "authenticated" if successful
- `principal_type`: The type of principal (e.g., "service user")
- `service_user_name`: The name of the service user
- `org_id`: Your organization ID

If authentication fails, it will return an error status with a message explaining the issue.

## Running with Docker

### Using Docker Compose (Recommended)

1. Create a `.env` file with your credentials:

```bash
cp .env.example .env
# Edit .env with your DEVIN_API_KEY, DEVIN_ORG_ID, and GITHUB_TOKEN
```

2. Build and run:

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`

### Using Docker directly

1. Build the image:

```bash
docker build -t agentic-devin-swe-remediation .
```

2. Run the container:

```bash
docker run -p 8000:8000 \
  -e DEVIN_API_KEY=your_devin_api_key \
  -e DEVIN_ORG_ID=your_devin_org_id \
  -e GITHUB_TOKEN=your_github_token \
  -v $(pwd)/data:/app/data \
  agentic-devin-swe-remediation
```

## Simulating Events

The `/simulate` endpoint allows local testing without a live GitHub webhook.

### Simulate a `risk:quality` Issue

```bash
python scripts/simulate_event.py \
  --owner emillaurence \
  --repo superset \
  --number 1 \
  --title "Fix code quality issue in utils module" \
  --body "There are linting errors in the utils module that need to be fixed." \
  --labels devin-remediate risk:quality
```

### Simulate a `risk:security` Issue

```bash
python scripts/simulate_event.py \
  --owner emillaurence \
  --repo superset \
  --number 2 \
  --title "Update vulnerable dependency" \
  --body "Security scan detected a vulnerable dependency that needs updating." \
  --labels devin-remediate risk:security
```

### Using curl

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

## Viewing Sessions and Metrics

### Agentic Software Engineering Control Tower

The system includes an executive-friendly control tower dashboard providing operational visibility from engineering issue signal to autonomous remediation and pull request review. Access it at:

```
http://localhost:8000/dashboard
```

The dashboard is designed for engineering leadership and answers the question: "Is agentic remediation creating engineering leverage by converting issue signals into reviewable pull requests faster, with governance and traceability?"

**Tab 1: Executive Overview (Default)**
- Value statement explaining the business impact of agentic remediation
- Headline KPI Cards (aligned to four business outcomes):
  - Productivity: Reviewable PRs Created - Number of Devin remediation sessions that produced a pull request
  - Resilience: Risk Issues in Remediation - Number of accepted remediation sessions with risk labels such as risk:security or risk:quality
  - Reliability: Issue-to-PR Conversion Rate - Reviewable PRs created divided by accepted GitHub Issues processed
  - Governance: PRs Awaiting Review - Sessions where Devin has produced a PR and human review is now required
- Operating Status Strip:
  - Active Remediations - Sessions where Devin is currently working and no PR has been created yet
  - Needs Triage - Sessions where Devin could not safely progress to a reviewable PR and needs engineer input
  - Mean Time to Reviewable PR - Average time from session creation to PR detection, where available
- Business Outcomes Panel:
  - Productivity - Reduces manual triage and repetitive remediation work so engineers can focus on higher-value delivery
  - Resilience - Accelerates remediation of quality and security issues before they accumulate into operational risk
  - Reliability - Tracks every GitHub Issue through agent execution, pull request creation, and review handoff
  - Governance - Keeps humans in control by making pull request review the merge gate
- Operating Health Strip - Shows healthy if no items need triage, needs attention otherwise

**Tab 2: Remediation Queue**
- Operational status view showing one row per issue/session
- Columns: Issue #, Issue Title, Repository, Risk Category, Current Status, PR Link, Last Updated
- Status mapping:
  - status:devin-running = Devin is actively working
  - status:needs-review = PR created, human review required
  - status:devin-completed = Devin session fully completed
  - status:devin-failed = Needs Triage
- Special handling: If a PR exists but the Devin session is still running, shows as "needs-review"

**Tab 3: Session Details**
- Detailed technical session information for senior ICs and technical reviewers
- Columns: Issue #, Title, Repository, All Labels, Risk Labels, Devin Status, Devin Status Detail, Internal App Status, Devin Session (clickable link), PR Link (clickable link), Error Message, Validation Summary, Created At, Updated At
- Devin Session links to https://app.devin.ai/sessions/{session_id}
- PR links open in new tab
- Raw session IDs available in /sessions endpoint for debugging

**Tab 4: Risk and Value**
- Breakdown of remediation work by risk category
- Categories: risk:quality, risk:security, Unclassified
- For each category: number of issues, number of PRs created, number awaiting review, number needing triage
- Executive explanation of where agentic remediation is being applied

**Design Features:**
- Clean dark enterprise SaaS look aligned with Cognition/Devin
- Color palette: Primary blue (#3969CA), Accent blue (#0294DE), Success green (#21C19A), Deep navy background (#0B1020)
- Responsive desktop layout
- Clickable GitHub issue, Devin session, and PR links
- No heavy frontend framework - self-contained HTML/CSS/vanilla JavaScript
- Reads directly from local JSON session store
- Refresh the page to see the latest data

**Why These KPIs Matter to Engineering Leaders:**
- **Productivity: Reviewable PRs Created** - Measures actual output and engineering leverage created by Devin, showing that the agent is producing usable engineering output
- **Resilience: Risk Issues in Remediation** - Shows how security and quality issues are being actively moved toward remediation before they accumulate into operational risk
- **Reliability: Issue-to-PR Conversion Rate** - Indicates how effectively the system converts accepted GitHub Issues into reviewable pull requests, demonstrating workflow reliability
- **Governance: PRs Awaiting Review** - Highlights where human attention is needed for governance, ensuring humans remain in control as the merge gate

**Needs Triage:**
This KPI tracks remediations where Devin could not safely progress to a reviewable PR and needs engineer input. These may include:
- Failed sessions due to errors or timeouts
- Suspended sessions requiring human input
- Blocked sessions that could not proceed
- Any state where Devin cannot safely continue or produce a reviewable PR

The underlying GitHub status label remains `status:devin-failed` for these sessions, but the dashboard uses the more descriptive "Needs Triage" terminology to clearly communicate that human attention is needed.

### View All Sessions

```bash
curl http://localhost:8000/sessions
```

Or visit `http://localhost:8000/sessions` in your browser.

### View Metrics

```bash
curl http://localhost:8000/metrics
```

Or visit `http://localhost:8000/metrics` in your browser.

Metrics include:
- Total issues processed
- Sessions running/needs_review/completed/failed
- Count by risk label
- Count by repository
- Average session duration
- Completion rate percentage
- Review queue size

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

**To enable automated completion:**
- Configure your GitHub webhook to send `Pull request` events to `https://your-domain.com/webhook/github/pull_request`
- The system will automatically detect merged PRs and complete the associated sessions

**Webhook Configuration Summary:**
- Issue webhook: `https://your-domain.com/webhook/github/issue` (triggers remediation)
- PR webhook: `https://your-domain.com/webhook/github/pull_request` (auto-completes sessions)

**Manual completion is still available:**
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

## Extending the System

### Additional Repositories

To support additional repositories, simply:

1. Update the `DEFAULT_GITHUB_OWNER` and `DEFAULT_GITHUB_REPO` environment variables
2. Or specify the owner/repo in the webhook payload or simulate request
3. The system is designed to work with any GitHub repository

### Additional Risk Labels

To add new risk labels:

1. Add the label to your GitHub repository
2. Update the `generate_prompt` method in `app/devin_client.py` to handle the new label
3. The system will automatically capture any label starting with `risk:` as a risk label

### Additional Remediation Workflows

To add new remediation workflows:

1. Define new trigger labels in environment variables
2. Update the webhook handler in `app/main.py` to check for additional trigger labels
3. Extend the prompt generation in `app/devin_client.py` to handle new workflow types
4. Add corresponding status labels if needed

### Webhook Configuration

To set up GitHub webhooks:

1. Go to your repository Settings → Webhooks
2. Add a new webhook pointing to your deployed endpoint: `https://your-domain.com/webhook/github`
3. Select "Issues" as the event type
4. Use a secret for security (add `GITHUB_WEBHOOK_SECRET` to your environment variables)

## Target Repository

The first supported target repository is:

https://github.com/emillaurence/superset

This is a fork of Apache Superset. The first test issue is issue #1: "Test Devin remediation workflow with a small code quality issue"

## Design Principles

- **Simple and Reliable**: First version focuses on core functionality with local JSON storage
- **Observable**: Clear logs for engineering leaders and senior engineers to understand the workflow
- **Extensible**: Label-driven design allows easy addition of new repos, labels, and workflows
- **Safe by Default**: Minimal changes, validation checks, and human oversight through GitHub comments

## License

Internal engineering automation system.
