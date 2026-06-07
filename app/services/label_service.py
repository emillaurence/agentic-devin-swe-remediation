import logging
from typing import List
from app.core.github_client import GitHubClient

logger = logging.getLogger(__name__)


class LabelService:
    """Service for managing GitHub labels and comments."""
    
    def __init__(self, github_client: GitHubClient):
        self.github_client = github_client
    
    async def remove_all_status_labels(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        status_labels: List[str]
    ):
        """Remove all status labels from an issue."""
        for label in status_labels:
            try:
                await self.github_client.remove_label(owner, repo, issue_number, label)
            except Exception as e:
                logger.warning(f"Failed to remove label '{label}': {e}")
    
    async def add_status_label(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        label: str
    ):
        """Add a status label to an issue."""
        await self.github_client.add_label(owner, repo, issue_number, label)
    
    async def transition_to_running(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        status_running_label: str,
        status_failed_label: str,
        status_completed_label: str,
        status_needs_review_label: str
    ):
        """Transition issue to running status by removing old labels and adding running label."""
        status_labels = [
            status_running_label,
            status_failed_label,
            status_completed_label,
            status_needs_review_label
        ]
        await self.remove_all_status_labels(owner, repo, issue_number, status_labels)
        await self.add_status_label(owner, repo, issue_number, status_running_label)
    
    async def transition_to_needs_review(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        status_running_label: str,
        status_failed_label: str,
        status_completed_label: str,
        status_needs_review_label: str
    ):
        """Transition issue to needs review status."""
        status_labels = [
            status_running_label,
            status_failed_label,
            status_completed_label,
            status_needs_review_label
        ]
        await self.remove_all_status_labels(owner, repo, issue_number, status_labels)
        await self.add_status_label(owner, repo, issue_number, status_needs_review_label)
    
    async def transition_to_failed(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        status_running_label: str,
        status_failed_label: str,
        status_completed_label: str,
        status_needs_review_label: str
    ):
        """Transition issue to failed status."""
        status_labels = [
            status_running_label,
            status_failed_label,
            status_completed_label,
            status_needs_review_label
        ]
        await self.remove_all_status_labels(owner, repo, issue_number, status_labels)
        await self.add_status_label(owner, repo, issue_number, status_failed_label)
    
    async def transition_to_completed(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        status_running_label: str,
        status_failed_label: str,
        status_completed_label: str,
        status_needs_review_label: str
    ):
        """Transition issue to completed status."""
        status_labels = [
            status_running_label,
            status_failed_label,
            status_completed_label,
            status_needs_review_label
        ]
        await self.remove_all_status_labels(owner, repo, issue_number, status_labels)
        await self.add_status_label(owner, repo, issue_number, status_completed_label)
    
    def build_start_comment(
        self,
        session_id: str,
        devin_session_url: str,
        risk_labels: List[str],
        status_running_label: str
    ) -> str:
        """Build the comment for when a remediation session starts."""
        risk_labels_str = ', '.join(risk_labels) if risk_labels else 'None'
        
        return f"""🤖 **Devin Remediation Started**

A Devin session has been created to address this issue.

**Session ID:** `{session_id}`
**Session URL:** {devin_session_url}
**Risk Labels:** {risk_labels_str}

Devin will:
- Inspect the repository and understand the issue
- Perform the smallest safe remediation aligned to the issue
- Run relevant validation checks
- Open a pull request with the changes
- Comment here with the PR link and validation results

This issue has been labeled `{status_running_label}`. Progress will be updated as the session completes.
"""
    
    def build_completion_comment(
        self,
        session_id: str,
        pull_request_url: str = None,
        validation_summary: str = None,
        status_needs_review_label: str = None
    ) -> str:
        """Build the comment for when a remediation session completes and needs review."""
        comment_body = f"""👀 **Devin Remediation Completed - Awaiting Review**

**Session ID:** `{session_id}`
**Status:** Devin has completed remediation and is awaiting human review

"""
        if pull_request_url:
            comment_body += f"**Pull Request:** {pull_request_url}\n\n"
        
        if validation_summary:
            comment_body += f"**Validation Summary:**\n{validation_summary}\n\n"
        
        comment_body += """Please review the pull request and validate the changes. Once approved, the session can be marked as completed.

This issue has been labeled `status:devin-needs-human-review`."""
        
        return comment_body
    
    def build_failure_comment(
        self,
        session_id: str,
        devin_state: str,
        failure_reason: str = None
    ) -> str:
        """Build the comment for when a remediation session fails."""
        comment_body = f"""❌ **Devin Remediation Failed**

**Session ID:** `{session_id}`
**Status:** {devin_state.capitalize()}
"""
        if failure_reason:
            comment_body += f"\n**Reason:** {failure_reason}\n\n"
        
        comment_body += "This issue has been labeled `status:devin-failed`."
        
        return comment_body
