import uuid
import logging
from datetime import datetime
from typing import List, Optional
from app.core.models import GitHubIssue, DevinSession, SessionStatus
from app.core.store import SessionStore
from app.core.devin_client import DevinClient
from app.core.github_client import GitHubClient
from app.services.label_service import LabelService

logger = logging.getLogger(__name__)


class SoftwareRemediationService:
    """Service for managing software remediation workflows with Devin."""
    
    def __init__(
        self,
        devin_client: Optional[DevinClient],
        github_client: Optional[GitHubClient],
        store: SessionStore,
        label_service: LabelService,
        status_running_label: str,
        status_failed_label: str,
        status_completed_label: str,
        status_needs_review_label: str
    ):
        self.devin_client = devin_client
        self.github_client = github_client
        self.store = store
        self.label_service = label_service
        self.status_running_label = status_running_label
        self.status_failed_label = status_failed_label
        self.status_completed_label = status_completed_label
        self.status_needs_review_label = status_needs_review_label
    
    async def process_remediation(self, issue: GitHubIssue, risk_labels: List[str]):
        """Process a remediation request by creating a Devin session."""
        
        logger.info(f"Processing remediation for {issue.owner}/{issue.repo}#{issue.number}")
        
        try:
            # Generate prompt for Devin
            if self.devin_client:
                prompt = self.devin_client.generate_prompt(issue, risk_labels)
            else:
                logger.error("Devin client not initialized - cannot create session")
                if self.github_client:
                    await self.github_client.add_label(issue.owner, issue.repo, issue.number, self.status_failed_label)
                    await self.github_client.add_comment(
                        issue.owner, issue.repo, issue.number,
                        "❌ Devin remediation failed: Devin client not initialized. Please check DEVIN_API_KEY."
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
            
            devin_response = await self.devin_client.create_session(prompt, session_metadata)
            session_id = devin_response.get("session_id", str(uuid.uuid4()))
            
            # Construct Devin session URL
            devin_session_url = f"https://app.devin.ai/sessions/{session_id}"
            
            # Create session record
            session = DevinSession(
                session_id=session_id,
                issue=issue,
                risk_labels=risk_labels,
                status=SessionStatus.RUNNING,
                prompt=prompt,
                devin_response=devin_response,
                devin_session_url=devin_session_url
            )
            
            self.store.add_session(session)
            
            # Add comment to GitHub issue
            if self.github_client:
                comment_body = self.label_service.build_start_comment(
                    session_id,
                    devin_session_url,
                    risk_labels,
                    self.status_running_label
                )
                await self.github_client.add_comment(issue.owner, issue.repo, issue.number, comment_body)
                
                # Transition labels to running status
                await self.label_service.transition_to_running(
                    issue.owner, issue.repo, issue.number,
                    self.status_running_label,
                    self.status_failed_label,
                    self.status_completed_label,
                    self.status_needs_review_label
                )
            
            logger.info(f"Successfully started Devin session {session_id} for issue {issue.number}")
            
        except Exception as e:
            logger.error(f"Error processing remediation for issue {issue.number}: {str(e)}", exc_info=True)
            
            # Update session status to failed
            existing_session = self.store.find_session_by_issue(issue.owner, issue.repo, issue.number)
            if existing_session:
                self.store.update_session(
                    existing_session.session_id,
                    {
                        "status": SessionStatus.FAILED,
                        "error_message": str(e),
                        "completed_at": datetime.utcnow()
                    }
                )
            
            # Add failure label and comment to GitHub
            if self.github_client:
                await self.github_client.add_label(issue.owner, issue.repo, issue.number, self.status_failed_label)
                await self.github_client.add_comment(
                    issue.owner, issue.repo, issue.number,
                    f"❌ Devin remediation failed: {str(e)}"
                )
    
    async def sync_sessions(self):
        """Sync all running Devin sessions with their actual status from Devin API.
        
        This function:
        - Gets all running sessions from the store
        - Queries Devin API for each session's current status
        - Updates local session records and GitHub labels based on status
        - Comments on GitHub issues with completion/failure details
        """
        if not self.devin_client:
            logger.warning("Devin client not initialized - cannot sync sessions")
            return
        
        logger.info("Starting session sync")
        
        # Get all running sessions
        all_sessions = self.store.get_all_sessions()
        running_sessions = [s for s in all_sessions if s.status == SessionStatus.RUNNING]
        
        logger.info(f"Found {len(running_sessions)} running sessions to sync")
        
        for session in running_sessions:
            try:
                logger.info(f"Checking status for session {session.session_id}")
                
                # Get session status from Devin
                session_status = await self.devin_client.get_session_status(session.session_id)
                
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
                    await self._handle_terminal_session(session, session_status, devin_state, has_pull_requests)
                else:
                    logger.info(f"Session {session.session_id} still running (status: {devin_state})")
                    
            except Exception as e:
                logger.error(f"Error syncing session {session.session_id}: {str(e)}", exc_info=True)
        
        # Verify and fix GitHub labels for sessions in needs_review status
        await self._verify_needs_review_labels(all_sessions)
        
        logger.info("Session sync completed")
    
    async def _handle_terminal_session(
        self,
        session: DevinSession,
        session_status: dict,
        devin_state: str,
        has_pull_requests: bool
    ):
        """Handle a session that has reached a terminal state."""
        # Determine final status
        if devin_state == "completed":
            # Transition to needs human review instead of directly to completed
            final_status = SessionStatus.NEEDS_HUMAN_REVIEW
            status_label = self.status_needs_review_label
        else:
            final_status = SessionStatus.FAILED
            status_label = self.status_failed_label
        
        # Extract additional info from Devin response
        pull_request_url = session_status.get("pull_request_url") or session.pull_request_url
        
        # If no pull_request_url but has pull_requests array, extract from there
        if not pull_request_url and has_pull_requests:
            pull_requests = session_status.get("pull_requests", [])
            if pull_requests:
                pull_request_url = pull_requests[0].get("url") if isinstance(pull_requests[0], dict) else str(pull_requests[0])
        
        # Fallback: Check GitHub for PRs if Devin API didn't return PR info
        if not pull_request_url and self.github_client and session.issue:
            try:
                logger.info(f"Devin API didn't return PR info, checking GitHub for PRs for issue {session.issue.number}")
                github_prs = await self.github_client.get_pull_requests_for_issue(
                    session.issue.owner, session.issue.repo, session.issue.number
                )
                if github_prs:
                    # Use the most recent PR
                    latest_pr = github_prs[0]  # GitHub returns PRs in reverse chronological order
                    pull_request_url = latest_pr.get("html_url")
                    logger.info(f"Found PR on GitHub: {pull_request_url}")
            except Exception as e:
                logger.error(f"Error checking GitHub for PRs: {str(e)}")
        
        validation_summary = session_status.get("validation_summary")
        failure_reason = session_status.get("error_message") or session_status.get("failure_reason")
        
        # Build comment body
        if final_status == SessionStatus.NEEDS_HUMAN_REVIEW:
            comment_body = self.label_service.build_completion_comment(
                session.session_id,
                pull_request_url,
                validation_summary,
                self.status_needs_review_label
            )
        else:
            comment_body = self.label_service.build_failure_comment(
                session.session_id,
                devin_state,
                failure_reason
            )
        
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
            # Set pr_detected_at if this is the first time we're detecting a PR
            if not session.pull_request_url:
                update_data["pr_detected_at"] = datetime.utcnow()
        
        if final_status == SessionStatus.FAILED and failure_reason:
            update_data["error_message"] = failure_reason
        
        self.store.update_session(session.session_id, update_data)
        
        # Update GitHub labels and add comment
        if self.github_client and session.issue:
            try:
                # Remove all status labels
                await self.label_service.remove_all_status_labels(
                    session.issue.owner, session.issue.repo, session.issue.number,
                    [self.status_running_label, self.status_completed_label, self.status_needs_review_label, self.status_failed_label]
                )
                
                # Add new status label
                await self.label_service.add_status_label(
                    session.issue.owner, session.issue.repo, session.issue.number, status_label
                )
                
                # Add comment
                await self.github_client.add_comment(session.issue.owner, session.issue.repo, session.issue.number, comment_body)
                
                logger.info(f"Updated GitHub issue {session.issue.number} for session {session.session_id}")
            except Exception as e:
                logger.error(f"Error updating GitHub for session {session.session_id}: {str(e)}")
        
        logger.info(f"Session {session.session_id} marked as {final_status.value}")
    
    async def _verify_needs_review_labels(self, all_sessions: List[DevinSession]):
        """Verify and fix GitHub labels for sessions in needs_review status."""
        needs_review_sessions = [s for s in all_sessions if s.status == SessionStatus.NEEDS_HUMAN_REVIEW]
        
        if needs_review_sessions and self.github_client:
            logger.info(f"Verifying GitHub labels for {len(needs_review_sessions)} sessions in needs_review status")
            
            for session in needs_review_sessions:
                try:
                    if not session.issue:
                        continue
                    
                    # Get current labels from GitHub
                    current_labels = await self.github_client.get_labels(session.issue.owner, session.issue.repo, session.issue.number)
                    current_label_names = [label.get("name") for label in current_labels]
                    
                    # Check if needs_review label is present
                    if self.status_needs_review_label not in current_label_names:
                        logger.warning(f"Session {session.session_id} is in needs_review status but missing {self.status_needs_review_label} label on GitHub")
                        
                        # Remove running label if present
                        if self.status_running_label in current_label_names:
                            await self.github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, self.status_running_label)
                        
                        # Add needs_review label
                        await self.github_client.add_label(session.issue.owner, session.issue.repo, session.issue.number, self.status_needs_review_label)
                        logger.info(f"Added {self.status_needs_review_label} label to issue {session.issue.number}")
                    
                    # Remove other status labels to avoid conflicts
                    for label in [self.status_running_label, self.status_completed_label, self.status_failed_label]:
                        if label in current_label_names and label != self.status_needs_review_label:
                            await self.github_client.remove_label(session.issue.owner, session.issue.repo, session.issue.number, label)
                            logger.info(f"Removed {label} label from issue {session.issue.number}")
                    
                except Exception as e:
                    logger.error(f"Error verifying GitHub labels for session {session.session_id}: {str(e)}", exc_info=True)
    
    def find_session_by_pr_url(self, pr_url: str, all_sessions: List[DevinSession]) -> Optional[DevinSession]:
        """Find a session by PR URL."""
        for session in all_sessions:
            if session.pull_request_url and session.pull_request_url == pr_url:
                return session
        return None
    
    def find_session_by_issue_reference(
        self,
        pr_title: str,
        pr_body: str,
        all_sessions: List[DevinSession]
    ) -> Optional[DevinSession]:
        """Find a session by issue number referenced in PR title or body."""
        import re
        issue_pattern = r'#(\d+)'
        
        # Search in title and body for issue numbers
        text_to_search = f"{pr_title} {pr_body}"
        issue_matches = re.findall(issue_pattern, text_to_search)
        
        # Try to match sessions by the referenced issue numbers
        for issue_ref in issue_matches:
            issue_number = int(issue_ref)
            for session in all_sessions:
                if session.issue and session.issue.number == issue_number:
                    logger.info(f"Found session {session.session_id} by matching issue number {issue_number} from PR")
                    return session
        
        return None
