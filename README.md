# Agentic Devin SWE Remediation

An event-driven remediation platform that helps engineering teams move from reactive issue management to an agentic operating model.

## Problem Context

Large engineering teams already have many signals from GitHub issues, dependency scans, static analysis, failing tests, and operational alerts. The problem is that these signals often stop at detection. Humans still need to triage, understand the codebase, apply fixes, validate changes, and open pull requests.

This system closes that gap by using Devin as an autonomous software engineering worker.

Traditional automation tells teams what is broken. Devin helps complete the engineering work.

## Architecture

The system is built as a Python FastAPI application with the following components:

- **FastAPI Application** (`app/main.py`): REST API endpoints for webhooks, simulation, and metrics
- **Devin Client** (`app/core/devin_client.py`): Integration with the Devin API for creating autonomous sessions
- **GitHub Client** (`app/core/github_client.py`): Integration with GitHub API for issue comments and label management
- **Session Store** (`app/core/store.py`): Local JSON-based storage for tracking Devin sessions
- **Data Models** (`app/core/models.py`): Pydantic models for issues, sessions, and metrics

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

## Complete Workflow Setup Guide

This section provides a step-by-step guide to set up and run the entire agentic remediation workflow from scratch.

### Prerequisites

- Python 3.11 or higher
- Devin API key and organization ID
- GitHub personal access token with repo permissions
- ngrok account (for local webhook testing)
- A GitHub repository to remediate issues in

### Step 1: Configure GitHub Repository Labels

Before running the application, you need to set up the required labels in your GitHub repository:

1. Go to your GitHub repository
2. Navigate to **Settings** → **Labels**
3. Create the following labels:

**Trigger Label:**
- `devin-remediate` - Add this to issues to trigger Devin remediation

**Risk/Category Labels:**
- `risk:security` - For security-focused remediation (dependencies, vulnerabilities)
- `risk:quality` - For quality-focused remediation (code quality, linting, static analysis)

**Status Labels:**
- `status:devin-running` - Automatically added when Devin starts (optional, system will create)
- `status:devin-needs-human-review` - Added when Devin completes and opens PR (optional, system will create)
- `status:devin-completed` - Added when remediation is approved (optional, system will create)
- `status:devin-failed` - Added when remediation fails (optional, system will create)

**Note:** The system will automatically create status labels if they don't exist, but creating them beforehand ensures consistency.

### Step 2: Set Up Environment Variables

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit `.env` and fill in the required values:

```bash
# Devin API Configuration
DEVIN_API_KEY=your_actual_devin_api_key
DEVIN_ORG_ID=your_actual_devin_org_id

# GitHub API Configuration
GITHUB_TOKEN=your_actual_github_token

# Default GitHub Repository (update to your target repo)
DEFAULT_GITHUB_OWNER=your_github_username
DEFAULT_GITHUB_REPO=your_target_repository

# Ngrok Configuration (optional, for local testing)
NGROK_AUTHTOKEN=your_ngrok_authtoken
```

**Getting your credentials:**

- **Devin API Key & Org ID**: Log in to https://app.devin.ai and get these from your account settings
- **GitHub Token**: Create a personal access token at https://github.com/settings/tokens with `repo` permissions
- **Ngrok Auth Token**: Sign up at https://ngrok.com and get your authtoken from the dashboard

### Step 3: Start the Application with Docker Compose (Recommended)

Docker Compose is the recommended way to run the application:

1. Build and run with Docker Compose:

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`

2. Verify it's running:

```bash
curl http://localhost:8000/health
```

You should see a response indicating the service is healthy.

3. To stop the application:

```bash
docker compose down
```

**Alternative: Manual Python Execution**

If you prefer to run the application manually without Docker:

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the FastAPI application:

```bash
python -m app.main
```

The API will be available at `http://localhost:8000`

### Step 5: Test Devin Authentication

Verify your Devin credentials are configured correctly:

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

### Step 6: Set Up ngrok for Local Webhook Testing

To receive GitHub webhooks locally, you need to expose your local server to the internet.

**Using Docker Compose (Automatic):**

ngrok is automatically configured when using Docker Compose. Just ensure you've added your ngrok authtoken to the `.env` file:

```bash
NGROK_AUTHTOKEN=your_ngrok_authtoken
```

When you run `docker compose up --build`, ngrok will automatically start and tunnel the app service. You'll see the ngrok URL in the docker compose logs.

**Alternative: Manual ngrok Setup**

If you're running the application manually without Docker Compose:

1. Install ngrok (if not already installed):
   ```bash
   # macOS
   brew install ngrok

   # Or download from https://ngrok.com
   ```

2. Authenticate ngrok (optional, but recommended for persistent URLs):
   ```bash
   ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN
   ```

3. Start ngrok to tunnel port 8000:
   ```bash
   ngrok http 8000
   ```

4. Copy the ngrok HTTPS URL (e.g., `https://abc123.ngrok.io`)

**Keep ngrok running** in a separate terminal window while testing.

### Step 7: Configure GitHub Webhooks

1. Go to your GitHub repository
2. Navigate to **Settings** → **Webhooks** → **Add webhook**
3. Configure the webhook:

**Payload URL:**
```
https://your-ngrok-url.ngrok.io/webhook/github/issue
```

**Content type:** `application/json`

**Secret:** (Optional) Create a secret and add `GITHUB_WEBHOOK_SECRET=your_secret` to your `.env` file

**Events:** Select only "Issues" (do not select "Pull requests" for this webhook)

**Active:** Check the box to enable the webhook

4. Click "Add webhook"

5. For automated PR completion, add a second webhook:
   - **Payload URL:** `https://your-ngrok-url.ngrok.io/webhook/github/pull_request`
   - **Events:** Select "Pull requests"

### Step 8: Test the Complete Workflow

Now test the end-to-end workflow:

1. **Create a test issue** in your GitHub repository with:
   - Title: "Test Devin remediation"
   - Description: "This is a test issue for the remediation workflow"
   - Labels: `devin-remediate` and `risk:quality` (or `risk:security`)

2. **Watch the logs** in your terminal where the app is running. You should see:
   - Webhook received
   - Devin session created
   - Status labels updated on GitHub

3. **Monitor progress**:
   - Check the dashboard: `http://localhost:8000/dashboard`
   - Check session status: `http://localhost:8000/sessions`
   - Check metrics: `http://localhost:8000/metrics`

4. **Verify GitHub updates**:
   - The issue should have `status:devin-running` label
   - A comment should be added indicating Devin is working
   - When Devin completes, a PR should be created
   - The issue should have `status:devin-needs-human-review` label

5. **Complete the workflow**:
   - Review the PR in GitHub
   - Merge the PR if satisfied
   - The system will automatically mark the session as completed
   - The issue should have `status:devin-completed` label

### Alternative: Test Without Webhooks (Simulation)

If you want to test without setting up webhooks, use the simulation endpoint:

```bash
python scripts/simulate_event.py \
  --owner your_github_username \
  --repo your_target_repository \
  --number 1 \
  --title "Test remediation" \
  --body "Test issue for remediation" \
  --labels devin-remediate risk:quality
```

This simulates a webhook event without requiring GitHub webhooks to be configured.

### Step 9: Monitor and Manage Sessions

**View all sessions:**
```bash
curl http://localhost:8000/sessions
```

**View sessions needing review:**
```bash
curl http://localhost:8000/sessions/review-queue
```

**Manually sync session status:**
```bash
curl -X POST http://localhost:8000/sessions/sync
```

**Manually mark a session as completed:**
```bash
curl -X POST http://localhost:8000/sessions/{session_id}/complete \
  -H "Content-Type: application/json" \
  -d '{"pull_request_url": "https://github.com/owner/repo/pull/123"}'
```

### Troubleshooting

**Webhook not triggering:**
- Check GitHub webhook delivery logs in Settings → Webhooks
- Verify ngrok is running and the URL is correct
- Check the application logs for errors

**Devin authentication failed:**
- Verify `DEVIN_API_KEY` and `DEVIN_ORG_ID` are correct
- Test with `curl http://localhost:8000/health/devin`

**GitHub API errors:**
- Verify `GITHUB_TOKEN` has proper `repo` permissions
- Check the token hasn't expired

**Session not updating:**
- Manually trigger sync: `curl -X POST http://localhost:8000/sessions/sync`
- Check the Devin session URL directly in the browser

### Production Deployment

For production use:

1. Deploy the application to a cloud provider (AWS, GCP, Azure, or Heroku)
2. Use environment variables for configuration (not `.env` file)
3. Configure GitHub webhooks to point to your production URL
4. Set up proper logging and monitoring
5. Consider using a database instead of local JSON storage for scalability

See "Running with Docker" below for containerized deployment options.

## Setup Instructions (Quick Reference)

### Prerequisites

- Docker and Docker Compose (recommended)
- Python 3.11 or higher (for manual execution)
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
- `BLENDED_ENGINEERING_HOURLY_COST=150` - Blended hourly cost for engineering time (default: 150)
- `ROI_CURRENCY=A$` - Currency symbol for ROI display (default: A$)

### Running with Docker Compose (Recommended)

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

3. To stop:

```bash
docker compose down
```

### Local Development (Manual)

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
- Hero KPI: Estimated Engineering Cost Saved - Financial value of engineering time saved through agentic remediation
- Headline KPI Cards (aligned to four business outcomes):
  - Productivity: Reviewable PRs Created - Number of Devin remediation sessions that produced a pull request
  - Resilience: Risk Issues in Remediation - Number of accepted remediation sessions with risk labels such as risk:security or risk:quality
  - Reliability: Issue-to-PR Conversion Rate - Reviewable PRs created divided by accepted GitHub Issues processed
  - Governance: PRs Awaiting Review - Sessions where Devin has produced a PR and human review is now required
- Operating Status Strip:
  - Active Remediations - Sessions where Devin is currently working and no PR has been created yet
  - Needs Triage (Failed) - Sessions where Devin could not safely progress to a reviewable PR and needs engineer input
  - Mean Time to Reviewable PR - Average time from session creation to PR detection, where available
- Operating Health Strip - Shows healthy if no items need triage, needs attention otherwise

**Tab 2: Remediation Queue**
- Operational status view showing one row per issue/session
- Columns: Issue #, Issue Title, Repository, Risk Category, Devin Status, PR Link, Last Updated
- Status mapping:
  - Running = Devin is actively working
  - Needs Human Review = PR created, human review required
  - Completed = Devin session fully completed
  - Needs Triage (Failed) = Session failed and needs engineer input

**Tab 3: Risk and Value**
- Breakdown of remediation work by risk category
- Categories: risk:quality, risk:security, Unclassified
- For each category: Cost Saved, Time Saved, number of issues, number of PRs created, number awaiting review, number needing triage (failed)
- Executive explanation of where agentic remediation is being applied

**Tab 4: Session Details**
- Detailed technical session information for senior ICs and technical reviewers
- Columns: Issue #, Title, Repository, All Labels, Risk Category, Devin Status, Devin Session (clickable link), PR Link (clickable link), Time to PR, Error Message, Created At, Updated At
- Devin Session links to https://app.devin.ai/sessions/{session_id}
- PR links open in new tab

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

**Needs Triage (Failed):**
This KPI tracks remediations where Devin could not safely progress to a reviewable PR and needs engineer input. These may include:
- Failed sessions due to errors or timeouts
- Suspended sessions requiring human input
- Blocked sessions that could not proceed
- Any state where Devin cannot safely continue or produce a reviewable PR

The underlying GitHub status label remains `status:devin-failed` for these sessions, but the dashboard uses the more descriptive "Needs Triage (Failed)" terminology to clearly communicate that human attention is needed.

## ROI Calculation

The dashboard calculates and displays **Estimated Engineering Cost Avoided** as the main hero metric in the Executive Overview. This represents the financial value of engineering time saved through agentic remediation.

### Calculation Method

Estimated Engineering Cost Avoided is calculated from actual time saved already tracked by the app:

```
Estimated Engineering Cost Avoided = actual_time_saved_hours × blended_engineering_hourly_cost
```

**Example:**
- Actual engineering time saved: 3.0 hrs
- Blended engineering hourly cost: A$150/hr
- Estimated Engineering Cost Avoided: A$450

### Configuration

The ROI calculation uses the following environment variables:

- `BLENDED_ENGINEERING_HOURLY_COST` - Blended hourly cost for engineering time (default: 150)
- `ROI_CURRENCY` - Currency symbol for ROI display (default: A$)

These can be overridden in your `.env` file to match your organization's cost structure and currency.

### Important Notes

- The value is calculated from actual or observed engineering time saved based on the remediation workflow timing already tracked by the app
- Sessions with "Needs Triage (Failed)" status are excluded from this calculation as they did not produce a productive PR
- This is for ROI modelling purposes only, not for billing
- The calculation uses the difference between human baseline hours and actual Devin execution time to determine actual time saved

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
2. Update the `generate_prompt` method in `app/core/devin_client.py` to handle the new label
3. The system will automatically capture any label starting with `risk:` as a risk label

### Additional Remediation Workflows

To add new remediation workflows:

1. Define new trigger labels in environment variables
2. Update the webhook handler in `app/main.py` to check for additional trigger labels
3. Extend the prompt generation in `app/core/devin_client.py` to handle new workflow types
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
