import logging
from typing import List
from app.core.models import WebhookPayload, GitHubIssue, IssueLabel

logger = logging.getLogger(__name__)


class WebhookService:
    """Service for parsing and validating GitHub webhook payloads."""
    
    def extract_risk_labels(self, labels: List[str]) -> List[str]:
        """Extract risk labels from a list of labels."""
        return [label for label in labels if label.startswith("risk:")]
    
    def parse_webhook_issue(self, payload: WebhookPayload) -> GitHubIssue:
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
    
    def should_process_webhook(
        self,
        payload: WebhookPayload,
        trigger_label: str
    ) -> tuple[bool, str]:
        """
        Determine if webhook should be processed.
        
        Returns:
            Tuple of (should_process, reason)
        """
        # Only process issue events
        if not payload.issue:
            return False, "not an issue event"
        
        # Only process when the action is "labeled"
        if payload.action != "labeled":
            return False, f"action is not 'labeled'"
        
        # Only process when the label being added is the trigger label
        label_added = payload.label.get("name") if payload.label else None
        if label_added != trigger_label:
            return False, f"label '{label_added}' is not trigger label"
        
        return True, "accepted"
    
    def has_trigger_label(self, issue: GitHubIssue, trigger_label: str) -> bool:
        """Check if issue has the trigger label."""
        label_names = [label.name for label in issue.labels]
        return trigger_label in label_names
