import os
import uuid
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
import uvicorn

from app.models import (
    WebhookPayload,
    SimulateRequest,
    DevinSession,
    GitHubIssue,
    IssueLabel,
    SessionStatus
)
from app.store import SessionStore
from app.devin_client import DevinClient
from app.github_client import GitHubClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
DEVIN_API_KEY = os.getenv("DEVIN_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DEFAULT_GITHUB_OWNER = os.getenv("DEFAULT_GITHUB_OWNER", "emillaurence")
DEFAULT_GITHUB_REPO = os.getenv("DEFAULT_GITHUB_REPO", "superset")
TRIGGER_LABEL = os.getenv("TRIGGER_LABEL", "devin-remediate")
STATUS_RUNNING_LABEL = os.getenv("STATUS_RUNNING_LABEL", "status:devin-running")
STATUS_COMPLETED_LABEL = os.getenv("STATUS_COMPLETED_LABEL", "status:devin-completed")
STATUS_FAILED_LABEL = os.getenv("STATUS_FAILED_LABEL", "status:devin-failed")
STORE_PATH = os.getenv("STORE_PATH", "./data/sessions.json")

# Validate required environment variables
if not DEVIN_API_KEY:
    logger.warning("DEVIN_API_KEY not set - Devin integration will not work")
if not GITHUB_TOKEN:
    logger.warning("GITHUB_TOKEN not set - GitHub API integration will not work")

# Initialize components
store = SessionStore(STORE_PATH)
devin_client = DevinClient(DEVIN_API_KEY) if DEVIN_API_KEY else None
github_client = GitHubClient(GITHUB_TOKEN) if GITHUB_TOKEN else None

# Create FastAPI app
app = FastAPI(
    title="Agentic Devin SWE Remediation",
    description="Event-driven remediation platform using Devin as an autonomous software engineering worker",
    version="1.0.0"
)


def extract_risk_labels(labels: List[str]) -> List[str]:
    """Extract risk labels from a list of labels."""
    risk_labels = [label for label in labels if label.startswith("risk:")]
    return risk_labels


def parse_webhook_issue(payload: WebhookPayload) -> GitHubIssue:
    """Parse GitHub issue from webhook payload."""
    issue_data = payload["issue"]
    repository_data = payload["repository"]
    
    owner = repository_data["owner"]["login"]
    repo = repository_data["name"]
    number = issue_data["number"]
    title = issue_data["title"]
    body = issue_data.get("body", "")
    url = issue_data["html_url"]
    
    labels = [
        IssueLabel(name=label_data["name"], color=label_data.get("color"))
        for label_data in issue_data.get("labels", [])
    ]
    
    return GitHubIssue(
        owner=owner,
        repo=repo,
        number=number,
        title=title,
        body=body,
        url=url,
        labels=labels
    )


async def process_remediation(issue: GitHubIssue, risk_labels: List[str]):
    """Process a remediation request by creating a Devin session."""
    
    logger.info(f"Processing remediation for {issue.owner}/{issue.repo}#{issue.number}")
    
    try:
        # Generate prompt for Devin
        if devin_client:
            prompt = devin_client.generate_prompt(issue, risk_labels)
        else:
            logger.error("Devin client not initialized - cannot create session")
            if github_client:
                await github_client.add_label(issue.owner, issue.repo, issue.number, STATUS_FAILED_LABEL)
                await github_client.add_comment(
                    issue.owner, issue.repo, issue.number,
                    f"❌ Devin remediation failed: Devin client not initialized. Please check DEVIN_API_KEY."
                )
            return
        
        # Create Devin session
        session_metadata = {
            "github_owner": issue.owner,
            "github_repo": issue.repo,
            "github_issue_number": issue.number,
            "github_issue_url": issue.url,
            "risk_labels": risk_labels,
            "triggered_at": datetime.utcnow().isoformat()
        }
        
        devin_response = await devin_client.create_session(prompt, session_metadata)
        session_id = devin_response.get("session_id", str(uuid.uuid4()))
        
        # Create session record
        session = DevinSession(
            session_id=session_id,
            issue=issue,
            risk_labels=risk_labels,
            status=SessionStatus.RUNNING,
            prompt=prompt,
            devin_response=devin_response
        )
        
        store.add_session(session)
        
        # Add comment to GitHub issue
        if github_client:
            comment_body = f"""🤖 **Devin Remediation Started**

A Devin session has been created to address this issue.

**Session ID:** `{session_id}`
**Risk Labels:** {', '.join(risk_labels) if risk_labels else 'None'}

Devin will:
- Inspect the repository and understand the issue
- Perform the smallest safe remediation aligned to the issue
- Run relevant validation checks
- Open a pull request with the changes
- Comment here with the PR link and validation results

This issue has been labeled `{STATUS_RUNNING_LABEL}`. Progress will be updated as the session completes.
"""
            await github_client.add_comment(issue.owner, issue.repo, issue.number, comment_body)
            await github_client.add_label(issue.owner, issue.repo, issue.number, STATUS_RUNNING_LABEL)
        
        logger.info(f"Successfully started Devin session {session_id} for issue {issue.number}")
        
    except Exception as e:
        logger.error(f"Error processing remediation for issue {issue.number}: {str(e)}", exc_info=True)
        
        # Update session status to failed
        existing_session = store.find_session_by_issue(issue.owner, issue.repo, issue.number)
        if existing_session:
            store.update_session(
                existing_session.session_id,
                {
                    "status": SessionStatus.FAILED,
                    "error_message": str(e),
                    "completed_at": datetime.utcnow()
                }
            )
        
        # Add failure label and comment to GitHub
        if github_client:
            await github_client.add_label(issue.owner, issue.repo, issue.number, STATUS_FAILED_LABEL)
            await github_client.add_comment(
                issue.owner, issue.repo, issue.number,
                f"❌ Devin remediation failed: {str(e)}"
            )


@app.post("/webhook/github")
async def github_webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    """
    Handle GitHub issue webhook events.
    
    This endpoint:
    - Detects when an issue has the trigger label
    - Captures issue metadata and risk labels
    - Avoids duplicate Devin sessions
    - Creates a Devin session
    - Records the session in the store
    - Comments back on the GitHub issue
    - Adds the status:devin-running label
    """
    
    logger.info(f"Received GitHub webhook: action={payload.get('action')}")
    
    # Only process issue events
    if "issue" not in payload:
        logger.info("Not an issue event, skipping")
        return {"status": "skipped", "reason": "not an issue event"}
    
    # Parse issue from webhook
    issue = parse_webhook_issue(payload)
    
    # Extract labels
    label_names = [label.name for label in issue.labels]
    logger.info(f"Issue {issue.number} has labels: {label_names}")
    
    # Check for trigger label
    if TRIGGER_LABEL not in label_names:
        logger.info(f"Issue {issue.number} does not have trigger label '{TRIGGER_LABEL}', skipping")
        return {"status": "skipped", "reason": f"trigger label '{TRIGGER_LABEL}' not present"}
    
    # Extract risk labels
    risk_labels = extract_risk_labels(label_names)
    logger.info(f"Risk labels for issue {issue.number}: {risk_labels}")
    
    # Check for existing session to avoid duplicates
    existing_session = store.find_session_by_issue(issue.owner, issue.repo, issue.number)
    if existing_session and existing_session.status == SessionStatus.RUNNING:
        logger.warning(f"Session {existing_session.session_id} already running for issue {issue.number}, skipping")
        return {"status": "skipped", "reason": "session already running"}
    
    # Process remediation in background
    background_tasks.add_task(process_remediation, issue, risk_labels)
    
    return {
        "status": "accepted",
        "issue_number": issue.number,
        "risk_labels": risk_labels,
        "message": "Remediation processing started"
    }


@app.post("/simulate")
async def simulate(request: SimulateRequest, background_tasks: BackgroundTasks):
    """
    Simulate a remediation event without a live GitHub webhook.
    
    This endpoint allows local testing by providing issue details directly.
    It triggers the same remediation logic as the GitHub webhook handler.
    """
    
    logger.info(f"Received simulation request for {request.owner}/{request.repo}#{request.number}")
    
    # Create GitHubIssue from request
    issue = GitHubIssue(
        owner=request.owner,
        repo=request.repo,
        number=request.number,
        title=request.title,
        body=request.body,
        url=request.url,
        labels=[IssueLabel(name=label) for label in request.labels]
    )
    
    # Extract risk labels
    risk_labels = extract_risk_labels(request.labels)
    logger.info(f"Risk labels for simulation: {risk_labels}")
    
    # Check for existing session to avoid duplicates
    existing_session = store.find_session_by_issue(request.owner, request.repo, request.number)
    if existing_session and existing_session.status == SessionStatus.RUNNING:
        logger.warning(f"Session {existing_session.session_id} already running for issue {request.number}, skipping")
        return {"status": "skipped", "reason": "session already running"}
    
    # Process remediation in background
    background_tasks.add_task(process_remediation, issue, risk_labels)
    
    return {
        "status": "accepted",
        "issue_number": request.number,
        "risk_labels": risk_labels,
        "message": "Remediation processing started"
    }


@app.get("/sessions")
async def get_sessions():
    """
    Return all tracked Devin sessions from the local JSON store.
    """
    sessions = store.get_all_sessions()
    return {
        "count": len(sessions),
        "sessions": [store._session_to_dict(session) for session in sessions]
    }


@app.get("/metrics")
async def get_metrics():
    """
    Return basic operational metrics.
    
    Metrics include:
    - Total issues processed
    - Sessions running/completed/failed
    - Count by risk label
    - Count by repository
    - Average duration
    """
    metrics = store.get_metrics()
    return {
        "total_issues_processed": metrics.total_issues_processed,
        "sessions_running": metrics.sessions_running,
        "sessions_completed": metrics.sessions_completed,
        "sessions_failed": metrics.sessions_failed,
        "count_by_risk_label": metrics.count_by_risk_label,
        "count_by_repository": metrics.count_by_repository,
        "average_duration_seconds": metrics.average_duration_seconds
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "devin_configured": devin_client is not None,
        "github_configured": github_client is not None
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
