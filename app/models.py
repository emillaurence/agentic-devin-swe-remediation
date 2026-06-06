from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    RUNNING = "running"
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
    prompt: str
    devin_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    pull_request_url: Optional[str] = None


class WebhookPayload(BaseModel):
    action: str
    issue: Dict[str, Any]
    repository: Dict[str, Any]
    sender: Dict[str, Any]


class SimulateRequest(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    body: str
    labels: List[str]
    url: str


class Metrics(BaseModel):
    total_issues_processed: int
    sessions_running: int
    sessions_completed: int
    sessions_failed: int
    count_by_risk_label: Dict[str, int]
    count_by_repository: Dict[str, int]
    average_duration_seconds: Optional[float] = None
