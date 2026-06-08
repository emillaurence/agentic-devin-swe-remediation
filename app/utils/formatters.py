from datetime import datetime
from typing import List, Dict, Any
import logging
from app.core.models import SessionStatus, DevinSession
from app.utils.config import RISK_LABEL_MAPPING, DEVIN_SESSION_URL_FORMAT, STATUS_DISPLAY_NAMES

logger = logging.getLogger(__name__)


def format_timestamp(ts) -> str:
    """Format a timestamp for display."""
    if ts is None:
        return "Unknown"
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def get_friendly_risk_label(risk_label: str) -> str:
    """Map a risk label to a friendly name."""
    if not risk_label:
        return "Unclassified"
    return RISK_LABEL_MAPPING.get(risk_label, "Unclassified")


def get_friendly_risk_category(risk_labels: List[str]) -> str:
    """Get friendly risk category from risk labels list."""
    if not risk_labels or len(risk_labels) == 0:
        return "Unclassified"
    # Return the first friendly label found
    for label in risk_labels:
        friendly = get_friendly_risk_label(label)
        if friendly != "Unclassified":
            return friendly
    return "Unclassified"


def get_display_status(session: DevinSession) -> str:
    """Determine display status for a session."""
    # If PR exists but Devin session is still running or waiting, show as needs-review
    if session.pull_request_url and session.status == SessionStatus.RUNNING:
        return STATUS_DISPLAY_NAMES["needs_human_review"]
    return STATUS_DISPLAY_NAMES.get(session.status.value, session.status.value)


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{int(seconds)} sec"
    elif seconds < 3600:
        return f"{int(seconds / 60)} min"
    else:
        return f"{int(seconds / 3600)} hr"


def calculate_kpis(sessions: List[DevinSession], config: Dict[str, Any] = None) -> Dict[str, Any]:
    """Calculate dashboard KPIs from sessions."""
    issues_processed = len(sessions)
    reviewable_prs_generated = len([s for s in sessions if s.pull_request_url])
    issue_signal_to_pr_conversion_rate = (reviewable_prs_generated / issues_processed * 100) if issues_processed > 0 else 0
    
    # Calculate time saved (human baseline hours - Devin time)
    # Exclude failed sessions from time saved calculation
    total_time_saved_hours = 0
    for session in sessions:
        # Skip failed sessions - they don't contribute to time saved
        if session.status == SessionStatus.FAILED:
            continue
        if session.pr_detected_at and session.created_at:
            try:
                # Handle both datetime objects and string timestamps
                pr_time = session.pr_detected_at if isinstance(session.pr_detected_at, datetime) else datetime.fromisoformat(session.pr_detected_at) if isinstance(session.pr_detected_at, str) else None
                created_time = session.created_at if isinstance(session.created_at, datetime) else datetime.fromisoformat(session.created_at) if isinstance(session.created_at, str) else None
                
                if pr_time and created_time:
                    devin_time_hours = (pr_time - created_time).total_seconds() / 3600
                    
                    # Determine baseline based on risk category
                    baseline_hours = config.get("HUMAN_BASELINE_OTHER_HOURS", 6) if config else 6
                    if session.risk_labels:
                        for label in session.risk_labels:
                            if label == "risk:quality":
                                baseline_hours = config.get("HUMAN_BASELINE_QUALITY_HOURS", 3) if config else 3
                                break
                            elif label == "risk:security":
                                baseline_hours = config.get("HUMAN_BASELINE_SECURITY_HOURS", 10) if config else 10
                                break
                    
                    time_saved = baseline_hours - devin_time_hours
                    total_time_saved_hours += time_saved
            except Exception as e:
                logger.warning(f"Error calculating time saved for session {session.session_id}: {e}")
                continue
    
    # Risk Issues in Remediation - accepted remediation sessions with risk labels
    risk_issues_in_remediation = len([s for s in sessions if s.risk_labels and len(s.risk_labels) > 0])
    
    # PRs awaiting engineering review - sessions with PR and status needs_review OR running with PR
    prs_awaiting_review = len([s for s in sessions if s.pull_request_url and (s.status == SessionStatus.NEEDS_HUMAN_REVIEW or s.status == SessionStatus.RUNNING)])
    
    # Needs Triage - failed, error, suspended, or needs intervention
    needs_triage = len([s for s in sessions if s.status == SessionStatus.FAILED])
    
    # Active Remediations - running with no PR yet
    active_remediations = len([s for s in sessions if s.status == SessionStatus.RUNNING and not s.pull_request_url])
    
    # Mean time from issue signal to PR
    pr_sessions = [s for s in sessions if s.pr_detected_at]
    if pr_sessions:
        total_time = sum((s.pr_detected_at - s.created_at).total_seconds() for s in pr_sessions)
        mean_time_to_pr_seconds = total_time / len(pr_sessions)
        mean_time_to_pr_minutes = int(mean_time_to_pr_seconds / 60)
    else:
        mean_time_to_pr_minutes = None
    
    # Operating health
    has_needs_triage = needs_triage > 0
    # Calculate completed sessions
    sessions_completed = len([s for s in sessions if s.status == SessionStatus.COMPLETED])
    # Only check conversion rate if there are completed sessions
    has_completed_sessions = sessions_completed > 0
    if has_completed_sessions:
        conversion_rate_threshold = 50  # 50% conversion rate is healthy
        is_healthy = issue_signal_to_pr_conversion_rate >= conversion_rate_threshold and not has_needs_triage
    else:
        # If no sessions completed yet, only check for failures
        is_healthy = not has_needs_triage
    
    # Calculate financial ROI from actual time saved
    blended_hourly_cost = config.get("BLENDED_ENGINEERING_HOURLY_COST", 150) if config else 150
    roi_currency = config.get("ROI_CURRENCY", "A$") if config else "A$"
    estimated_cost_avoided = round(total_time_saved_hours * blended_hourly_cost, 0)
    
    return {
        "reviewable_prs_generated": reviewable_prs_generated,
        "risk_issues_in_remediation": risk_issues_in_remediation,
        "issue_signal_to_pr_conversion_rate": issue_signal_to_pr_conversion_rate,
        "prs_awaiting_review": prs_awaiting_review,
        "needs_triage": needs_triage,
        "active_remediations": active_remediations,
        "mean_time_to_pr_minutes": mean_time_to_pr_minutes,
        "is_healthy": is_healthy,
        "sessions_completed": sessions_completed,
        "time_saved_hours": round(total_time_saved_hours, 1),
        "estimated_cost_avoided": estimated_cost_avoided,
        "roi_currency": roi_currency,
        "blended_hourly_cost": blended_hourly_cost
    }


def prepare_queue_rows(sessions: List[DevinSession], config: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Prepare data for the Remediation Queue tab."""
    queue_rows = []
    devin_org_slug = config.get("DEVIN_ORG_SLUG") if config else None
    
    for session in sessions:
        display_status = get_display_status(session)
        
        # Extract playbook ID from prefix if present
        playbook_id_clean = None
        playbook_link = None
        playbook_type_display = None
        # Check playbook_id at top level first, then in devin_response
        playbook_id = session.playbook_id or (session.devin_response.get("playbook_id") if session.devin_response else None)
        if playbook_id and devin_org_slug:
            # Remove "playbook-" prefix if present
            if playbook_id.startswith("playbook-"):
                playbook_id_clean = playbook_id.replace("playbook-", "", 1)
            else:
                playbook_id_clean = playbook_id
            # Create playbook link
            playbook_link = f"https://app.devin.ai/org/{devin_org_slug}/settings/playbooks/{playbook_id_clean}"
        
        # Format playbook type with proper case
        if session.playbook_type:
            playbook_type_display = session.playbook_type.capitalize()
        
        queue_rows.append({
            "issue_number": session.issue.number,
            "issue_title": session.issue.title,
            "issue_url": session.issue.url,
            "repository": f"{session.issue.owner}/{session.issue.repo}",
            "risk_labels": session.risk_labels if session.risk_labels else [],
            "risk_category": get_friendly_risk_category(session.risk_labels),
            "status": display_status,
            "pr_link": session.pull_request_url,
            "created_at": format_timestamp(session.created_at),
            "updated_at": format_timestamp(session.completed_at or session.needs_review_at or session.pr_detected_at or session.created_at),
            "playbook_link": playbook_link,
            "playbook_type_display": playbook_type_display,
            "playbook_type": session.playbook_type
        })
    
    queue_rows.sort(key=lambda x: x["created_at"], reverse=True)
    return queue_rows


def prepare_detail_rows(sessions: List[DevinSession], config: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Prepare data for the Session Details tab."""
    detail_rows = []
    devin_org_slug = config.get("DEVIN_ORG_SLUG") if config else None
    logger.info(f"prepare_detail_rows: devin_org_slug={devin_org_slug}")
    
    for session in sessions:
        all_labels = [label.name for label in session.issue.labels]
        display_status = get_display_status(session)
        
        # Format playbook type with proper case
        playbook_type_display = None
        if session.playbook_type:
            playbook_type_display = session.playbook_type.capitalize()
        
        # Extract playbook ID from prefix if present
        playbook_id_clean = None
        playbook_link = None
        # Check playbook_id at top level first, then in devin_response
        playbook_id = session.playbook_id or (session.devin_response.get("playbook_id") if session.devin_response else None)
        if playbook_id and devin_org_slug:
            # Remove "playbook-" prefix if present
            if playbook_id.startswith("playbook-"):
                playbook_id_clean = playbook_id.replace("playbook-", "", 1)
            else:
                playbook_id_clean = playbook_id
            # Create playbook link
            playbook_link = f"https://app.devin.ai/org/{devin_org_slug}/settings/playbooks/{playbook_id_clean}"
        
        detail_rows.append({
            "session_id": session.session_id,
            "issue_number": session.issue.number,
            "issue_title": session.issue.title,
            "issue_url": session.issue.url,
            "repository": f"{session.issue.owner}/{session.issue.repo}",
            "all_labels": all_labels,
            "risk_labels": session.risk_labels if session.risk_labels else [],
            "risk_category": get_friendly_risk_category(session.risk_labels),
            "status": display_status,
            "devin_status_detail": session.devin_response.get("status_detail") if session.devin_response else None,
            "devin_session_url": session.devin_session_url or DEVIN_SESSION_URL_FORMAT.format(session_id=session.session_id),
            "pr_link": session.pull_request_url,
            "pr_detected_at": session.pr_detected_at,
            "error_message": session.error_message,
            "created_at": format_timestamp(session.created_at),
            "updated_at": format_timestamp(session.completed_at or session.needs_review_at or session.pr_detected_at or session.created_at),
            "duration": None,  # Could calculate if needed
            "playbook_type": session.playbook_type,
            "playbook_type_display": playbook_type_display,
            "playbook_link": playbook_link
        })
    
    detail_rows.sort(key=lambda x: x["created_at"], reverse=True)
    return detail_rows


def prepare_risk_categories(sessions: List[DevinSession], config: Dict[str, Any] = None) -> Dict[str, Dict[str, Any]]:
    """Prepare data for the Risk and Value tab."""
    blended_hourly_cost = config.get("BLENDED_ENGINEERING_HOURLY_COST", 150) if config else 150
    roi_currency = config.get("ROI_CURRENCY", "A$") if config else "A$"
    
    risk_categories = {
        "Quality": {"issues": 0, "prs": 0, "awaiting_review": 0, "blocked": 0, "time_saved_hours": 0.0, "cost_saved": 0.0, "roi_currency": roi_currency},
        "Security": {"issues": 0, "prs": 0, "awaiting_review": 0, "blocked": 0, "time_saved_hours": 0.0, "cost_saved": 0.0, "roi_currency": roi_currency},
        "Unclassified": {"issues": 0, "prs": 0, "awaiting_review": 0, "blocked": 0, "time_saved_hours": 0.0, "cost_saved": 0.0, "roi_currency": roi_currency}
    }
    
    for session in sessions:
        friendly_category = get_friendly_risk_category(session.risk_labels)
        if friendly_category in risk_categories:
            risk_categories[friendly_category]["issues"] += 1
            if session.pull_request_url:
                risk_categories[friendly_category]["prs"] += 1
            display_status = get_display_status(session)
            if display_status == "needs-review":
                risk_categories[friendly_category]["awaiting_review"] += 1
            if session.status == SessionStatus.FAILED:
                risk_categories[friendly_category]["blocked"] += 1
            
            # Calculate time saved for this session
            # Exclude failed sessions from time saved calculation
            if session.status != SessionStatus.FAILED and session.pr_detected_at and session.created_at:
                try:
                    pr_time = session.pr_detected_at if isinstance(session.pr_detected_at, datetime) else datetime.fromisoformat(session.pr_detected_at) if isinstance(session.pr_detected_at, str) else None
                    created_time = session.created_at if isinstance(session.created_at, datetime) else datetime.fromisoformat(session.created_at) if isinstance(session.created_at, str) else None
                    
                    if pr_time and created_time:
                        devin_time_hours = (pr_time - created_time).total_seconds() / 3600
                        
                        # Determine baseline based on risk category
                        baseline_hours = config.get("HUMAN_BASELINE_OTHER_HOURS", 6) if config else 6
                        if session.risk_labels:
                            for label in session.risk_labels:
                                if label == "risk:quality":
                                    baseline_hours = config.get("HUMAN_BASELINE_QUALITY_HOURS", 3) if config else 3
                                    break
                                elif label == "risk:security":
                                    baseline_hours = config.get("HUMAN_BASELINE_SECURITY_HOURS", 10) if config else 10
                                    break
                        
                        time_saved = baseline_hours - devin_time_hours
                        risk_categories[friendly_category]["time_saved_hours"] += time_saved
                        risk_categories[friendly_category]["cost_saved"] += time_saved * blended_hourly_cost
                except Exception as e:
                    logger.warning(f"Error calculating time saved for session {session.session_id}: {e}")
                    continue
    
    return risk_categories
