from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    RUNNING = "running"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    COMPLETED = "completed"
    FAILED = "failed"


class IssueLabel(BaseModel):
    name: str
    color: Optional[str] = None


class GitHubIssue(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    body: str
    url: str
    labels: List[IssueLabel]


class DevinSession(BaseModel):
    session_id: str
    issue: GitHubIssue
    risk_labels: List[str] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.RUNNING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    needs_review_at: Optional[datetime] = None
    pr_detected_at: Optional[datetime] = None
    prompt: str
    devin_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    pull_request_url: Optional[str] = None
    devin_session_url: Optional[str] = None
    playbook_id: Optional[str] = None
    playbook_type: Optional[str] = None


class WebhookPayload(BaseModel):
    action: Optional[str] = None
    issue: Optional[Dict[str, Any]] = None
    repository: Optional[Dict[str, Any]] = None
    sender: Optional[Dict[str, Any]] = None
    label: Optional[Dict[str, Any]] = None
    zen: Optional[str] = None  # GitHub ping event


class SimulateRequest(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    body: str
    labels: List[str]
    url: str


class PullRequestWebhookPayload(BaseModel):
    action: Optional[str] = None
    pull_request: Optional[Dict[str, Any]] = None
    repository: Optional[Dict[str, Any]] = None
    sender: Optional[Dict[str, Any]] = None
    number: Optional[int] = None
    zen: Optional[str] = None  # GitHub ping event
    # Allow additional fields from GitHub webhook
    class Config:
        extra = "allow"


class Metrics(BaseModel):
    total_issues_processed: int
    sessions_running: int
    sessions_needs_review: int
    sessions_completed: int
    sessions_failed: int
    count_by_risk_label: Dict[str, int]
    count_by_repository: Dict[str, int]
    average_duration_seconds: Optional[float] = None
