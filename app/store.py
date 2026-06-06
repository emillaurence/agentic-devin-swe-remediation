import json
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.models import DevinSession, SessionStatus, Metrics
import logging

logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(self, store_path: str):
        self.store_path = store_path
        self._ensure_store_exists()

    def _ensure_store_exists(self):
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        if not os.path.exists(self.store_path):
            self._write_data([])

    def _read_data(self) -> List[Dict[str, Any]]:
        try:
            with open(self.store_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"Could not read store at {self.store_path}, initializing empty")
            return []

    def _write_data(self, data: List[Dict[str, Any]]):
        with open(self.store_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def _session_to_dict(self, session: DevinSession) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "issue": {
                "owner": session.issue.owner,
                "repo": session.issue.repo,
                "number": session.issue.number,
                "title": session.issue.title,
                "body": session.issue.body,
                "url": session.issue.url,
                "labels": [{"name": label.name, "color": label.color} for label in session.issue.labels]
            },
            "risk_labels": session.risk_labels,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            "prompt": session.prompt,
            "devin_response": session.devin_response,
            "error_message": session.error_message,
            "pull_request_url": session.pull_request_url
        }

    def _dict_to_session(self, data: Dict[str, Any]) -> DevinSession:
        from app.models import GitHubIssue, IssueLabel
        return DevinSession(
            session_id=data["session_id"],
            issue=GitHubIssue(
                owner=data["issue"]["owner"],
                repo=data["issue"]["repo"],
                number=data["issue"]["number"],
                title=data["issue"]["title"],
                body=data["issue"]["body"],
                url=data["issue"]["url"],
                labels=[IssueLabel(name=label["name"], color=label.get("color")) for label in data["issue"]["labels"]]
            ),
            risk_labels=data.get("risk_labels", []),
            status=SessionStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            prompt=data["prompt"],
            devin_response=data.get("devin_response"),
            error_message=data.get("error_message"),
            pull_request_url=data.get("pull_request_url")
        )

    def add_session(self, session: DevinSession) -> DevinSession:
        data = self._read_data()
        data.append(self._session_to_dict(session))
        self._write_data(data)
        logger.info(f"Added session {session.session_id} to store")
        return session

    def get_session(self, session_id: str) -> Optional[DevinSession]:
        data = self._read_data()
        for session_data in data:
            if session_data["session_id"] == session_id:
                return self._dict_to_session(session_data)
        return None

    def get_all_sessions(self) -> List[DevinSession]:
        data = self._read_data()
        return [self._dict_to_session(session_data) for session_data in data]

    def update_session(self, session_id: str, updates: Dict[str, Any]) -> Optional[DevinSession]:
        data = self._read_data()
        for i, session_data in enumerate(data):
            if session_data["session_id"] == session_id:
                for key, value in updates.items():
                    if key == "status":
                        session_data[key] = value.value if isinstance(value, SessionStatus) else value
                    elif key == "completed_at" and value:
                        session_data[key] = value.isoformat() if isinstance(value, datetime) else value
                    else:
                        session_data[key] = value
                self._write_data(data)
                logger.info(f"Updated session {session_id} with {updates.keys()}")
                return self._dict_to_session(session_data)
        return None

    def find_session_by_issue(self, owner: str, repo: str, issue_number: int) -> Optional[DevinSession]:
        data = self._read_data()
        for session_data in data:
            if (session_data["issue"]["owner"] == owner and
                session_data["issue"]["repo"] == repo and
                session_data["issue"]["number"] == issue_number):
                return self._dict_to_session(session_data)
        return None

    def get_metrics(self) -> Metrics:
        sessions = self.get_all_sessions()
        
        total_issues_processed = len(sessions)
        sessions_running = len([s for s in sessions if s.status == SessionStatus.RUNNING])
        sessions_completed = len([s for s in sessions if s.status == SessionStatus.COMPLETED])
        sessions_failed = len([s for s in sessions if s.status == SessionStatus.FAILED])
        
        count_by_risk_label: Dict[str, int] = {}
        for session in sessions:
            for label in session.risk_labels:
                count_by_risk_label[label] = count_by_risk_label.get(label, 0) + 1
        
        count_by_repository: Dict[str, int] = {}
        for session in sessions:
            repo_key = f"{session.issue.owner}/{session.issue.repo}"
            count_by_repository[repo_key] = count_by_repository.get(repo_key, 0) + 1
        
        # Calculate average duration for completed sessions
        completed_sessions = [s for s in sessions if s.completed_at and s.status == SessionStatus.COMPLETED]
        if completed_sessions:
            total_duration = sum((s.completed_at - s.created_at).total_seconds() for s in completed_sessions)
            average_duration_seconds = total_duration / len(completed_sessions)
        else:
            average_duration_seconds = None
        
        return Metrics(
            total_issues_processed=total_issues_processed,
            sessions_running=sessions_running,
            sessions_completed=sessions_completed,
            sessions_failed=sessions_failed,
            count_by_risk_label=count_by_risk_label,
            count_by_repository=count_by_repository,
            average_duration_seconds=average_duration_seconds
        )
