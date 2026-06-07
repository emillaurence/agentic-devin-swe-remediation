import os
import uuid
import logging
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app.models import (
    WebhookPayload,
    SimulateRequest,
    PullRequestWebhookPayload,
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
DEVIN_ORG_ID = os.getenv("DEVIN_ORG_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DEFAULT_GITHUB_OWNER = os.getenv("DEFAULT_GITHUB_OWNER", "emillaurence")
DEFAULT_GITHUB_REPO = os.getenv("DEFAULT_GITHUB_REPO", "superset")
TRIGGER_LABEL = os.getenv("TRIGGER_LABEL", "devin-remediate")
STATUS_RUNNING_LABEL = os.getenv("STATUS_RUNNING_LABEL", "status:devin-running")
STATUS_NEEDS_REVIEW_LABEL = os.getenv("STATUS_NEEDS_REVIEW_LABEL", "status:devin-needs-human-review")
STATUS_COMPLETED_LABEL = os.getenv("STATUS_COMPLETED_LABEL", "status:devin-completed")
STATUS_FAILED_LABEL = os.getenv("STATUS_FAILED_LABEL", "status:devin-failed")
STORE_PATH = os.getenv("STORE_PATH", "./data/sessions.json")

# Validate required environment variables
if not DEVIN_API_KEY:
    logger.warning("DEVIN_API_KEY not set - Devin integration will not work")
if not DEVIN_ORG_ID:
    logger.warning("DEVIN_ORG_ID not set - Devin integration will not work")
if not GITHUB_TOKEN:
    logger.warning("GITHUB_TOKEN not set - GitHub API integration will not work")

# Initialize components
store = SessionStore(STORE_PATH)
devin_client = DevinClient(DEVIN_API_KEY, DEVIN_ORG_ID) if DEVIN_API_KEY and DEVIN_ORG_ID else None
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
    issue_data = payload.issue
    repository_data = payload.repository
    
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
            # Remove all old status labels before adding running label
            await github_client.remove_label(issue.owner, issue.repo, issue.number, STATUS_RUNNING_LABEL)
            await github_client.remove_label(issue.owner, issue.repo, issue.number, STATUS_FAILED_LABEL)
            await github_client.remove_label(issue.owner, issue.repo, issue.number, STATUS_COMPLETED_LABEL)
            await github_client.remove_label(issue.owner, issue.repo, issue.number, STATUS_NEEDS_REVIEW_LABEL)
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


async def sync_sessions():
    """Sync all running Devin sessions with their actual status from Devin API.
    
    This function:
    - Gets all running sessions from the store
    - Queries Devin API for each session's current status
    - Updates local session records and GitHub labels based on status
    - Comments on GitHub issues with completion/failure details
    """
    if not devin_client:
        logger.warning("Devin client not initialized - cannot sync sessions")
        return
    
    logger.info("Starting session sync")
    
    # Get all running sessions
    all_sessions = store.get_all_sessions()
    running_sessions = [s for s in all_sessions if s.status == SessionStatus.RUNNING]
    
    logger.info(f"Found {len(running_sessions)} running sessions to sync")
    
    for session in running_sessions:
        try:
            logger.info(f"Checking status for session {session.session_id}")
            
            # Get session status from Devin
            session_status = await devin_client.get_session_status(session.session_id)
            
            # Determine the actual status from Devin response
            # Devin API returns status field with values like: running, completed, failed, suspended, error
            devin_state = session_status.get("status", "").lower()
            
            logger.info(f"Session {session.session_id} Devin status: {devin_state}")
            
            # Check if session is terminal (completed, failed, suspended, error)
            terminal_states = ["completed", "failed", "suspended", "error"]
            
            # Also check for pull_requests as a completion signal (Devin API may not update status correctly)
            has_pull_requests = session_status.get("pull_requests") and len(session_status.get("pull_requests", [])) > 0
            
            # Consider session completed if it has pull requests, even if status is still "new" or "running"
            if has_pull_requests and devin_state in ["new", "running"]:
                logger.info(f"Session {session.session_id} has pull requests but status is '{devin_state}' - treating as completed")
                devin_state = "completed"
            
            if devin_state in terminal_states:
                # Determine final status
                if devin_state == "completed":
                    # Transition to needs human review instead of directly to completed
                    final_status = SessionStatus.NEEDS_HUMAN_REVIEW
                    status_label = STATUS_NEEDS_REVIEW_LABEL
                    emoji = "👀"
                else:
                    final_status = SessionStatus.FAILED
                    status_label = STATUS_FAILED_LABEL
                    emoji = "❌"
                
                # Extract additional info from Devin response
                pull_request_url = session_status.get("pull_request_url") or session.pull_request_url
                
                # If no pull_request_url but has pull_requests array, extract from there
                if not pull_request_url and has_pull_requests:
                    pull_requests = session_status.get("pull_requests", [])
                    if pull_requests:
                        pull_request_url = pull_requests[0].get("url") if isinstance(pull_requests[0], dict) else str(pull_requests[0])
                
                validation_summary = session_status.get("validation_summary")
                failure_reason = session_status.get("error_message") or session_status.get("failure_reason")
                
                # Build comment body
                if final_status == SessionStatus.NEEDS_HUMAN_REVIEW:
                    comment_body = f"""{emoji} **Devin Remediation Completed - Awaiting Review**

**Session ID:** `{session.session_id}`
**Status:** Devin has completed remediation and is awaiting human review

"""
                    if pull_request_url:
                        comment_body += f"**Pull Request:** {pull_request_url}\n\n"
                    
                    if validation_summary:
                        comment_body += f"**Validation Summary:**\n{validation_summary}\n\n"
                    
                    comment_body += """Please review the pull request and validate the changes. Once approved, the session can be marked as completed.

This issue has been labeled `status:devin-needs-human-review`."""
                else:
                    comment_body = f"""{emoji} **Devin Remediation Failed**

**Session ID:** `{session.session_id}`
**Status:** {devin_state.capitalize()}
"""
                    if failure_reason:
                        comment_body += f"\n**Reason:** {failure_reason}\n\n"
                    
                    comment_body += "This issue has been labeled `status:devin-failed`."
                
                # Update session in store
                update_data = {
                    "status": final_status
                }
                
                if final_status == SessionStatus.NEEDS_HUMAN_REVIEW:
                    update_data["needs_review_at"] = datetime.utcnow()
                elif final_status == SessionStatus.FAILED:
                    update_data["completed_at"] = datetime.utcnow()
                
                if pull_request_url:
                    update_data["pull_request_url"] = pull_request_url
                
                if final_status == SessionStatus.FAILED and failure_reason:
                    update_data["error_message"] = failure_reason
                
                store.update_session(session.session_id, update_data)
                
                # Update GitHub labels and add comment
                if github_client and session.issue:
                    try:
                        # Remove running label
                        await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_RUNNING_LABEL)
                        
                        # Remove other status labels to avoid conflicts
                        await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_COMPLETED_LABEL)
                        await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_NEEDS_REVIEW_LABEL)
                        await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_FAILED_LABEL)
                        
                        # Add new status label
                        await github_client.add_label(session.issue.owner, session.issue.repo, session.issue.number, status_label)
                        
                        # Add comment
                        await github_client.add_comment(session.issue.owner, session.issue.repo, session.issue.number, comment_body)
                        
                        logger.info(f"Updated GitHub issue {session.issue.number} for session {session.session_id}")
                    except Exception as e:
                        logger.error(f"Error updating GitHub for session {session.session_id}: {str(e)}")
                
                logger.info(f"Session {session.session_id} marked as {final_status.value}")
            else:
                logger.info(f"Session {session.session_id} still running (status: {devin_state})")
                
        except Exception as e:
            logger.error(f"Error syncing session {session.session_id}: {str(e)}", exc_info=True)
    
    # Verify and fix GitHub labels for sessions in needs_review status
    needs_review_sessions = [s for s in all_sessions if s.status == SessionStatus.NEEDS_HUMAN_REVIEW]
    
    if needs_review_sessions and github_client:
        logger.info(f"Verifying GitHub labels for {len(needs_review_sessions)} sessions in needs_review status")
        
        for session in needs_review_sessions:
            try:
                if not session.issue:
                    continue
                
                # Get current labels from GitHub
                current_labels = await github_client.get_labels(session.issue.owner, session.issue.repo, session.issue.number)
                current_label_names = [label.get("name") for label in current_labels]
                
                # Check if needs_review label is present
                if STATUS_NEEDS_REVIEW_LABEL not in current_label_names:
                    logger.warning(f"Session {session.session_id} is in needs_review status but missing {STATUS_NEEDS_REVIEW_LABEL} label on GitHub")
                    
                    # Remove running label if present
                    if STATUS_RUNNING_LABEL in current_label_names:
                        await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_RUNNING_LABEL)
                    
                    # Add needs_review label
                    await github_client.add_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_NEEDS_REVIEW_LABEL)
                    logger.info(f"Added {STATUS_NEEDS_REVIEW_LABEL} label to issue {session.issue.number}")
                
                # Remove other status labels to avoid conflicts
                for label in [STATUS_RUNNING_LABEL, STATUS_COMPLETED_LABEL, STATUS_FAILED_LABEL]:
                    if label in current_label_names and label != STATUS_NEEDS_REVIEW_LABEL:
                        await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, label)
                        logger.info(f"Removed {label} label from issue {session.issue.number}")
                
            except Exception as e:
                logger.error(f"Error verifying GitHub labels for session {session.session_id}: {str(e)}", exc_info=True)
    
    logger.info("Session sync completed")


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
    
    logger.info(f"Received GitHub webhook: action={payload.action}")
    
    # Only process issue events
    if not payload.issue:
        logger.info("Not an issue event, skipping")
        return {"status": "skipped", "reason": "not an issue event"}
    
    # Only process when the action is "labeled"
    if payload.action != "labeled":
        logger.info(f"Action is '{payload.action}', not 'labeled', skipping")
        return {"status": "skipped", "reason": "action is not 'labeled'"}
    
    # Only process when the label being added is the trigger label
    # This prevents loops when we add our own status labels
    label_added = payload.label.get("name") if payload.label else None
    if label_added != TRIGGER_LABEL:
        logger.info(f"Label '{label_added}' was added, not trigger label '{TRIGGER_LABEL}', skipping")
        return {"status": "skipped", "reason": f"label '{label_added}' is not trigger label"}
    
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


@app.post("/webhook/github/pull_request")
async def github_pull_request_webhook(payload: PullRequestWebhookPayload):
    """
    Handle GitHub pull request webhook events.
    
    This endpoint:
    - Detects when a pull request is merged
    - Finds the associated Devin session by PR URL
    - Automatically marks the session as completed
    - Updates GitHub labels to status:devin-completed
    """
    
    logger.info(f"Received GitHub pull request webhook: action={payload.action}")
    
    # Only process when the action is "closed" (which includes merged)
    if payload.action != "closed":
        logger.info(f"Action is '{payload.action}', not 'closed', skipping")
        return {"status": "skipped", "reason": "action is not 'closed'"}
    
    # Check if the PR was merged (not just closed without merging)
    pr_data = payload.pull_request
    is_merged = pr_data.get("merged", False)
    
    if not is_merged:
        logger.info("PR was closed but not merged, skipping")
        return {"status": "skipped", "reason": "PR was not merged"}
    
    # Extract PR URL
    pr_url = pr_data.get("html_url")
    if not pr_url:
        logger.error("PR URL not found in webhook payload")
        return {"status": "error", "reason": "PR URL not found"}
    
    logger.info(f"PR merged: {pr_url}")
    
    # Find the associated session by PR URL
    all_sessions = store.get_all_sessions()
    matching_session = None
    
    for session in all_sessions:
        if session.pull_request_url and session.pull_request_url == pr_url:
            matching_session = session
            break
    
    if not matching_session:
        logger.warning(f"No session found with PR URL: {pr_url}")
        return {"status": "skipped", "reason": "no session found with this PR URL"}
    
    # Only process sessions in needs_review status
    if matching_session.status != SessionStatus.NEEDS_HUMAN_REVIEW:
        logger.info(f"Session {matching_session.session_id} is not in needs_review status (current: {matching_session.status}), skipping")
        return {"status": "skipped", "reason": "session not in needs_review status"}
    
    logger.info(f"Found session {matching_session.session_id} for merged PR, marking as completed")
    
    # Update session status to completed
    update_data = {
        "status": SessionStatus.COMPLETED,
        "completed_at": datetime.utcnow()
    }
    
    store.update_session(matching_session.session_id, update_data)
    
    # Update GitHub labels
    if github_client and matching_session.issue:
        try:
            # Remove old status labels
            await github_client.remove_label(matching_session.issue.owner, matching_session.issue.repo, matching_session.issue.number, STATUS_RUNNING_LABEL)
            await github_client.remove_label(matching_session.issue.owner, matching_session.issue.repo, matching_session.issue.number, STATUS_NEEDS_REVIEW_LABEL)
            await github_client.remove_label(matching_session.issue.owner, matching_session.issue.repo, matching_session.issue.number, STATUS_FAILED_LABEL)
            
            # Add completed label
            await github_client.add_label(matching_session.issue.owner, matching_session.issue.repo, matching_session.issue.number, STATUS_COMPLETED_LABEL)
            
            # Add comment
            comment_body = f"""✅ **Devin Remediation Completed**

**Session ID:** `{matching_session.session_id}`
**Status:** Pull request merged successfully

**Pull Request:** {pr_url}

This issue has been labeled `status:devin-completed`. The remediation is complete.
"""
            await github_client.add_comment(matching_session.issue.owner, matching_session.issue.repo, matching_session.issue.number, comment_body)
            
            logger.info(f"Updated GitHub issue {matching_session.issue.number} for session {matching_session.session_id}")
        except Exception as e:
            logger.error(f"Error updating GitHub for session {matching_session.session_id}: {str(e)}")
    
    return {
        "status": "completed",
        "session_id": matching_session.session_id,
        "pr_url": pr_url
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


@app.get("/sessions/review-queue")
async def get_review_queue():
    """
    Return all sessions that need human review.
    
    This endpoint returns sessions with status 'needs_human_review',
    providing a filtered view of the review queue for engineering leaders.
    """
    sessions = store.get_all_sessions()
    review_sessions = [s for s in sessions if s.status == SessionStatus.NEEDS_HUMAN_REVIEW]
    return {
        "count": len(review_sessions),
        "sessions": [store._session_to_dict(session) for session in review_sessions]
    }


@app.get("/metrics")
async def get_metrics():
    """
    Return basic operational metrics.
    
    Metrics include:
    - Total issues processed
    - Sessions running/needs_review/completed/failed
    - Count by risk label
    - Count by repository
    - Average duration
    - Completion rate
    - Review queue size
    
    Note: Metrics reflect the latest synced statuses from the local store.
    To ensure metrics are up-to-date, call POST /sessions/sync before querying metrics.
    """
    # Sync sessions first to ensure metrics reflect latest status
    await sync_sessions()
    
    metrics = store.get_metrics()
    
    # Calculate completion rate
    total_finished = metrics.sessions_completed + metrics.sessions_failed
    completion_rate = (metrics.sessions_completed / total_finished * 100) if total_finished > 0 else 0
    
    # Review queue size is sessions_needs_review
    review_queue_size = metrics.sessions_needs_review
    
    return {
        "total_issues_processed": metrics.total_issues_processed,
        "sessions_running": metrics.sessions_running,
        "sessions_needs_human_review": metrics.sessions_needs_review,
        "sessions_completed": metrics.sessions_completed,
        "sessions_failed": metrics.sessions_failed,
        "count_by_risk_label": metrics.count_by_risk_label,
        "count_by_repository": metrics.count_by_repository,
        "average_duration_seconds": metrics.average_duration_seconds,
        "completion_rate_percent": round(completion_rate, 2),
        "review_queue_size": review_queue_size
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "devin_configured": devin_client is not None,
        "github_configured": github_client is not None
    }


@app.get("/health/devin")
async def devin_health_check():
    """
    Check Devin API authentication status.
    
    This endpoint verifies Devin authentication without creating a session.
    Returns service user name and org ID, but never returns the API key.
    """
    if not devin_client:
        return {
            "status": "not_configured",
            "message": "Devin client not initialized. Please check DEVIN_API_KEY and DEVIN_ORG_ID."
        }
    
    try:
        auth_info = await devin_client.check_authentication()
        return {
            "status": "authenticated",
            "principal_type": auth_info.get("principal_type"),
            "service_user_name": auth_info.get("service_user_name"),
            "org_id": auth_info.get("org_id")
        }
    except ValueError as e:
        return {
            "status": "authentication_failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Error checking Devin health: {str(e)}")
        return {
            "status": "error",
            "message": f"Error checking Devin authentication: {str(e)}"
        }


@app.post("/sessions/{session_id}/needs-review")
async def mark_session_needs_review(session_id: str):
    """
    Mark a Devin session as needing human review.
    
    This endpoint is called when Devin has completed remediation and opened a PR,
    but the changes require human review before being considered complete.
    """
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update session status
    update_data = {
        "status": SessionStatus.NEEDS_HUMAN_REVIEW,
        "needs_review_at": datetime.utcnow()
    }
    
    store.update_session(session_id, update_data)
    
    # Update GitHub issue label if configured
    if github_client and session.issue:
        try:
            # Remove running label
            await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_RUNNING_LABEL)
            # Add needs review label
            await github_client.add_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_NEEDS_REVIEW_LABEL)
        except Exception as e:
            logger.error(f"Error updating GitHub labels: {str(e)}")
    
    return {
        "status": "updated",
        "session_id": session_id,
        "new_status": "needs_human_review"
    }


@app.post("/sessions/{session_id}/complete")
async def complete_session(session_id: str, pull_request_url: Optional[str] = None):
    """
    Manually mark a Devin session as completed.
    
    This endpoint allows manually updating session status when Devin has completed
    work but the system hasn't detected it via polling yet.
    """
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update session status
    update_data = {
        "status": SessionStatus.COMPLETED,
        "completed_at": datetime.utcnow()
    }
    
    if pull_request_url:
        update_data["pull_request_url"] = pull_request_url
    
    store.update_session(session_id, update_data)
    
    # Update GitHub issue label if configured
    if github_client and session.issue:
        try:
            # Remove old status labels
            await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_RUNNING_LABEL)
            await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_NEEDS_REVIEW_LABEL)
            await github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_FAILED_LABEL)
            # Add completed label
            await github_client.add_label(session.issue.owner, session.issue.repo, session.issue.number, STATUS_COMPLETED_LABEL)
        except Exception as e:
            logger.error(f"Error updating GitHub labels: {str(e)}")
    
    return {
        "status": "updated",
        "session_id": session_id,
        "new_status": "completed"
    }


@app.post("/sessions/sync")
async def sync_sessions_endpoint():
    """
    Manually trigger a sync pass over all running Devin sessions.
    
    This endpoint:
    - Queries the Devin API for all running sessions
    - Updates local session records based on actual Devin status
    - Updates GitHub labels and comments for completed/failed sessions
    
    This is a polling-based mechanism, not a webhook callback from Devin.
    """
    await sync_sessions()
    
    # Return summary of sync
    all_sessions = store.get_all_sessions()
    running_count = len([s for s in all_sessions if s.status == SessionStatus.RUNNING])
    needs_review_count = len([s for s in all_sessions if s.status == SessionStatus.NEEDS_HUMAN_REVIEW])
    completed_count = len([s for s in all_sessions if s.status == SessionStatus.COMPLETED])
    failed_count = len([s for s in all_sessions if s.status == SessionStatus.FAILED])
    
    return {
        "status": "synced",
        "sessions_checked": running_count + needs_review_count + completed_count + failed_count,
        "sessions_running": running_count,
        "sessions_needs_review": needs_review_count,
        "sessions_completed": completed_count,
        "sessions_failed": failed_count
    }


async def periodic_sync():
    """Periodically sync running Devin sessions every 60 seconds."""
    while True:
        try:
            await sync_sessions()
        except Exception as e:
            logger.error(f"Error in periodic sync: {str(e)}", exc_info=True)
        await asyncio.sleep(10)


@app.on_event("startup")
async def startup_event():
    """Start the periodic sync task on startup."""
    logger.info("Starting periodic sync task")
    asyncio.create_task(periodic_sync())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
