import logging
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app.core.models import (
    WebhookPayload,
    SimulateRequest,
    PullRequestWebhookPayload,
    SessionStatus
)
from app.core.store import SessionStore
from app.core.devin_client import DevinClient
from app.core.github_client import GitHubClient
from app.utils.config import load_environment_variables, initialize_components
from app.services.webhook_service import WebhookService
from app.services.label_service import LabelService
from app.services.software_remediation_service import SoftwareRemediationService
from app.utils.formatters import (
    calculate_kpis,
    prepare_queue_rows,
    prepare_detail_rows,
    prepare_risk_categories,
    format_duration
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load configuration
config = load_environment_variables()
components = initialize_components(config)

store = components["store"]
devin_client = components["devin_client"]
github_client = components["github_client"]

# Initialize services
webhook_service = WebhookService()
label_service = LabelService(github_client) if github_client else None
remediation_service = SoftwareRemediationService(
    devin_client=devin_client,
    github_client=github_client,
    store=store,
    label_service=label_service,
    status_running_label=config["STATUS_RUNNING_LABEL"],
    status_failed_label=config["STATUS_FAILED_LABEL"],
    status_completed_label=config["STATUS_COMPLETED_LABEL"],
    status_needs_review_label=config["STATUS_NEEDS_REVIEW_LABEL"],
    config=config
) if github_client else None

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# Create FastAPI app
app = FastAPI(
    title="Agentic Devin SWE Remediation",
    description="Event-driven remediation platform using Devin as an autonomous software engineering worker",
    version="1.0.0"
)


async def process_remediation(issue, risk_labels):
    """Process a remediation request by creating a Devin session."""
    if remediation_service:
        await remediation_service.process_remediation(issue, risk_labels)


async def sync_sessions():
    """Sync all running Devin sessions with their actual status from Devin API."""
    if remediation_service:
        await remediation_service.sync_sessions()


@app.post("/webhook/github/issue")
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
    
    # Handle GitHub ping events
    if payload.zen or not payload.action:
        logger.info("Received ping event, skipping")
        return {"status": "pong"}
    
    # Use webhook service to validate
    should_process, reason = webhook_service.should_process_webhook(payload, config["TRIGGER_LABEL"])
    
    if not should_process:
        logger.info(f"Skipping webhook: {reason}")
        return {"status": "skipped", "reason": reason}
    
    # Parse issue from webhook
    issue = webhook_service.parse_webhook_issue(payload)
    
    # Extract labels
    label_names = [label.name for label in issue.labels]
    logger.info(f"Issue {issue.number} has labels: {label_names}")
    
    # Check for trigger label
    if not webhook_service.has_trigger_label(issue, config["TRIGGER_LABEL"]):
        logger.info(f"Issue {issue.number} does not have trigger label '{config['TRIGGER_LABEL']}', skipping")
        return {"status": "skipped", "reason": f"trigger label '{config['TRIGGER_LABEL']}' not present"}
    
    # Extract risk labels
    risk_labels = webhook_service.extract_risk_labels(label_names)
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
async def github_pull_request_webhook(request: Request):
    """
    Handle GitHub pull request webhook events.

    This endpoint:
    - Detects when a pull request is merged
    - Finds the associated Devin session by PR URL
    - Automatically marks the session as completed
    - Updates GitHub labels to status:devin-completed
    """

    # Log raw payload for debugging
    raw_payload = await request.json()
    logger.info(f"Received GitHub pull request webhook raw payload: {raw_payload}")

    try:
        payload = PullRequestWebhookPayload(**raw_payload)
    except Exception as e:
        logger.error(f"Failed to parse GitHub pull request webhook payload: {e}")
        logger.error(f"Webhook payload validation failed. Ensure the payload structure matches GitHub's pull request webhook format.")
        raise

    logger.info(f"Parsed webhook payload: action={payload.action}")

    # Handle GitHub ping events
    if payload.zen or not payload.action:
        logger.info("Received ping event, skipping")
        return {"status": "pong"}

    # Handle PR reopened action - reset session status from failed to needs_review
    if payload.action == "reopened":
        logger.info("PR reopened, checking if session needs status reset")
        
        pr_data = payload.pull_request
        pr_url = pr_data.get("html_url")
        
        if not pr_url:
            logger.error("PR URL not found in webhook payload")
            return {"status": "error", "reason": "PR URL not found"}
        
        # Find the associated session by PR URL or issue number
        all_sessions = store.get_all_sessions()
        matching_session = None
        
        if remediation_service:
            matching_session = remediation_service.find_session_by_pr_url(pr_url, all_sessions)
            
            if not matching_session and pr_data:
                pr_title = pr_data.get("title", "")
                pr_body = pr_data.get("body", "")
                matching_session = remediation_service.find_session_by_issue_reference(pr_title, pr_body, all_sessions)
        
        if matching_session and matching_session.status == SessionStatus.FAILED:
            logger.info(f"Resetting session {matching_session.session_id} from failed to needs_review after PR reopen")
            
            update_data = {
                "status": SessionStatus.NEEDS_HUMAN_REVIEW,
                "needs_review_at": datetime.utcnow(),
                "error_message": None
            }
            
            store.update_session(matching_session.session_id, update_data)
            
            # Update GitHub labels
            if label_service and matching_session.issue:
                try:
                    await label_service.transition_to_needs_review(
                        matching_session.issue.owner,
                        matching_session.issue.repo,
                        matching_session.issue.number,
                        config["STATUS_RUNNING_LABEL"],
                        config["STATUS_FAILED_LABEL"],
                        config["STATUS_COMPLETED_LABEL"],
                        config["STATUS_NEEDS_REVIEW_LABEL"]
                    )
                    
                    await github_client.add_comment(
                        matching_session.issue.owner,
                        matching_session.issue.repo,
                        matching_session.issue.number,
                        f"🔄 **PR Reopened**\n\nThe pull request has been reopened. The session status has been reset from failed to needs review.\n\n**Session ID:** `{matching_session.session_id}`\n**PR URL:** {pr_url}"
                    )
                    
                    logger.info(f"Reset session {matching_session.session_id} to needs_review status")
                except Exception as e:
                    logger.error(f"Error updating GitHub for session {matching_session.session_id}: {str(e)}")
            
            return {
                "status": "reset",
                "session_id": matching_session.session_id,
                "pr_url": pr_url
            }
        
        return {"status": "skipped", "reason": "no failed session found for this PR"}

    # Only process when the action is "closed" (which includes merged)
    if payload.action != "closed":
        logger.info(f"Action is '{payload.action}', not 'closed', skipping")
        return {"status": "skipped", "reason": "action is not 'closed'"}
    
    # Extract PR data
    pr_data = payload.pull_request
    pr_url = pr_data.get("html_url")
    if not pr_url:
        logger.error("PR URL not found in webhook payload")
        return {"status": "error", "reason": "PR URL not found"}
    
    # Check if the PR was merged (not just closed without merging)
    is_merged = pr_data.get("merged", False)
    
    if not is_merged:
        logger.info("PR was closed but not merged, marking session as failed")
        
        # Find the associated session by PR URL or issue number
        all_sessions = store.get_all_sessions()
        matching_session = None
        
        # First try to match by PR URL
        if remediation_service:
            matching_session = remediation_service.find_session_by_pr_url(pr_url, all_sessions)
        
        # If no match by PR URL, try to extract issue number from PR body/title
        if not matching_session and pr_data and remediation_service:
            pr_title = pr_data.get("title", "")
            pr_body = pr_data.get("body", "")
            matching_session = remediation_service.find_session_by_issue_reference(pr_title, pr_body, all_sessions)
        
        if not matching_session:
            logger.warning(f"No session found with PR URL: {pr_url}")
            return {"status": "skipped", "reason": "no session found with this PR URL"}
        
        # Only process sessions in needs_review status
        if matching_session.status != SessionStatus.NEEDS_HUMAN_REVIEW:
            logger.info(f"Session {matching_session.session_id} is not in needs_review status (current: {matching_session.status}), skipping")
            return {"status": "skipped", "reason": "session not in needs_review status"}
        
        logger.info(f"Found session {matching_session.session_id} for closed PR, marking as failed")
        
        # Update session status to failed
        update_data = {
            "status": SessionStatus.FAILED,
            "completed_at": datetime.utcnow(),
            "error_message": "Pull request was closed without merging (changes rejected)"
        }
        
        # Store the PR URL if it wasn't already stored
        if not matching_session.pull_request_url:
            update_data["pull_request_url"] = pr_url
            logger.info(f"Storing PR URL for session {matching_session.session_id}: {pr_url}")
        
        store.update_session(matching_session.session_id, update_data)
        
        # Update GitHub labels
        if label_service and matching_session.issue:
            try:
                await label_service.transition_to_failed(
                    matching_session.issue.owner,
                    matching_session.issue.repo,
                    matching_session.issue.number,
                    config["STATUS_RUNNING_LABEL"],
                    config["STATUS_FAILED_LABEL"],
                    config["STATUS_COMPLETED_LABEL"],
                    config["STATUS_NEEDS_REVIEW_LABEL"]
                )
                
                # Add comment about rejection
                await github_client.add_comment(
                    matching_session.issue.owner,
                    matching_session.issue.repo,
                    matching_session.issue.number,
                    f"❌ **Devin Remediation Rejected**\n\nThe pull request was closed without merging. The session has been marked as failed.\n\n**Session ID:** `{matching_session.session_id}`\n**PR URL:** {pr_url}"
                )
                
                logger.info(f"Updated GitHub labels for issue {matching_session.issue.number} - marked as failed")
            except Exception as e:
                logger.error(f"Error updating GitHub for session {matching_session.session_id}: {str(e)}")
        
        return {
            "status": "failed",
            "session_id": matching_session.session_id,
            "pr_url": pr_url
        }
    
    logger.info(f"PR merged: {pr_url}")
    
    # Find the associated session by PR URL or issue number
    all_sessions = store.get_all_sessions()
    matching_session = None
    
    # First try to match by PR URL
    if remediation_service:
        matching_session = remediation_service.find_session_by_pr_url(pr_url, all_sessions)
    
    # If no match by PR URL, try to extract issue number from PR body/title
    if not matching_session and pr_data and remediation_service:
        pr_title = pr_data.get("title", "")
        pr_body = pr_data.get("body", "")
        matching_session = remediation_service.find_session_by_issue_reference(pr_title, pr_body, all_sessions)
    
    if not matching_session:
        logger.warning(f"No session found with PR URL: {pr_url}")
        return {"status": "skipped", "reason": "no session found with this PR URL"}
    
    # Only process sessions in needs_review or failed status
    if matching_session.status not in [SessionStatus.NEEDS_HUMAN_REVIEW, SessionStatus.FAILED]:
        logger.info(f"Session {matching_session.session_id} is not in needs_review or failed status (current: {matching_session.status}), skipping")
        return {"status": "skipped", "reason": "session not in needs_review or failed status"}
    
    logger.info(f"Found session {matching_session.session_id} for merged PR, marking as completed")
    
    # Update session status to completed
    update_data = {
        "status": SessionStatus.COMPLETED,
        "completed_at": datetime.utcnow()
    }
    
    # Store the PR URL if it wasn't already stored
    if not matching_session.pull_request_url:
        update_data["pull_request_url"] = pr_url
        logger.info(f"Storing PR URL for session {matching_session.session_id}: {pr_url}")
    
    store.update_session(matching_session.session_id, update_data)
    
    # Update GitHub labels
    if label_service and matching_session.issue:
        try:
            await label_service.transition_to_completed(
                matching_session.issue.owner,
                matching_session.issue.repo,
                matching_session.issue.number,
                config["STATUS_RUNNING_LABEL"],
                config["STATUS_FAILED_LABEL"],
                config["STATUS_COMPLETED_LABEL"],
                config["STATUS_NEEDS_REVIEW_LABEL"]
            )
            logger.info(f"Updated GitHub labels for issue {matching_session.issue.number} - marked as completed")
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
    from app.core.models import GitHubIssue, IssueLabel
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
    risk_labels = webhook_service.extract_risk_labels(request.labels)
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
            "message": "Failed to check Devin authentication. Check DEVIN_API_KEY and DEVIN_ORG_ID are valid."
        }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """
    Agentic Software Engineering Control Tower.
    
    Executive-friendly dashboard providing operational visibility for autonomous remediation
    from issue signal to pull request review.
    """
    # Get all sessions
    sessions = store.get_all_sessions()
    
    # Calculate KPIs using formatter utilities
    kpis = calculate_kpis(sessions, config)
    
    # Prepare data for tabs using formatter utilities
    queue_rows = prepare_queue_rows(sessions, config)
    detail_rows = prepare_detail_rows(sessions, config)
    risk_categories = prepare_risk_categories(sessions, config)
    
    # Calculate time to PR for detail rows
    for row in detail_rows:
        if row["pr_detected_at"] and row["created_at"]:
            try:
                pr_time = datetime.fromisoformat(row["pr_detected_at"]) if isinstance(row["pr_detected_at"], str) else row["pr_detected_at"]
                created_time = datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"]
                if pr_time and created_time:
                    time_diff = (pr_time - created_time).total_seconds()
                    row["time_to_pr"] = format_duration(time_diff)
            except Exception as e:
                row["time_to_pr"] = "N/A"
        else:
            row["time_to_pr"] = "N/A"
    
    # Render template
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "sessions": sessions,
        "kpis": kpis,
        "queue_rows": queue_rows,
        "detail_rows": detail_rows,
        "risk_categories": risk_categories
    })


@app.post("/sessions/{session_id}/needs-review")
async def mark_session_needs_review(session_id: str):
    """
    Mark a Devin session as needing human review.
    
    This endpoint is called when Devin has completed remediation and opened a PR,
    but the changes require human review before being considered complete.
    """
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found. Verify the session ID is correct.")
    
    # Update session status
    update_data = {
        "status": SessionStatus.NEEDS_HUMAN_REVIEW,
        "needs_review_at": datetime.utcnow()
    }
    
    store.update_session(session_id, update_data)
    
    # Update GitHub issue label if configured
    if label_service and session.issue:
        try:
            await label_service.transition_to_needs_review(
                session.issue.owner,
                session.issue.repo,
                session.issue.number,
                config["STATUS_RUNNING_LABEL"],
                config["STATUS_FAILED_LABEL"],
                config["STATUS_COMPLETED_LABEL"],
                config["STATUS_NEEDS_REVIEW_LABEL"]
            )
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
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found. Verify the session ID is correct.")
    
    # Update session status
    update_data = {
        "status": SessionStatus.COMPLETED,
        "completed_at": datetime.utcnow()
    }
    
    if pull_request_url:
        update_data["pull_request_url"] = pull_request_url
    
    store.update_session(session_id, update_data)
    
    # Update GitHub issue label if configured
    if label_service and session.issue:
        try:
            await label_service.transition_to_completed(
                session.issue.owner,
                session.issue.repo,
                session.issue.number,
                config["STATUS_RUNNING_LABEL"],
                config["STATUS_FAILED_LABEL"],
                config["STATUS_COMPLETED_LABEL"],
                config["STATUS_NEEDS_REVIEW_LABEL"]
            )
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
    """Periodically sync running Devin sessions every 5 seconds."""
    while True:
        try:
            await sync_sessions()
        except Exception as e:
            logger.error(f"Error in periodic sync: {str(e)}", exc_info=True)
        await asyncio.sleep(5)


@app.on_event("startup")
async def startup_event():
    """Start the periodic sync task on startup."""
    logger.info("Starting periodic sync task")
    asyncio.create_task(periodic_sync())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
