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

- `POST /webhook/github` - Accept GitHub issue webhook payloads (only triggers on `action == "labeled"`)
- `POST /simulate` - Simulate remediation events without live webhooks
- `GET /sessions` - View all tracked Devin sessions
- `GET /metrics` - View operational metrics
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
- `status:devin-completed` - Added when remediation completes successfully
- `status:devin-failed` - Added when remediation fails

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
- Sessions running/completed/failed
- Count by risk label
- Count by repository
- Average session duration

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
