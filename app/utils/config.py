import os
import logging
from app.core.devin_client import DevinClient
from app.core.github_client import GitHubClient
from app.core.store import SessionStore

logger = logging.getLogger(__name__)

# Risk label mapping for display
RISK_LABEL_MAPPING = {
    "risk:quality": "Quality",
    "risk:security": "Security"
}

# Devin session URL format
DEVIN_SESSION_URL_FORMAT = "https://app.devin.ai/sessions/{session_id}"

# Status display names for dashboard
STATUS_DISPLAY_NAMES = {
    "running": "Running",
    "needs_human_review": "Needs Human Review",
    "completed": "Completed",
    "failed": "Needs Triage"
}


def load_environment_variables():
    """Load and validate environment variables."""
    DEVIN_API_KEY = os.getenv("DEVIN_API_KEY")
    DEVIN_ORG_ID = os.getenv("DEVIN_ORG_ID")
    DEVIN_ORG_SLUG = os.getenv("DEVIN_ORG_SLUG")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    DEFAULT_GITHUB_OWNER = os.getenv("DEFAULT_GITHUB_OWNER", "emillaurence")
    DEFAULT_GITHUB_REPO = os.getenv("DEFAULT_GITHUB_REPO", "superset")
    TRIGGER_LABEL = os.getenv("TRIGGER_LABEL", "devin-remediate")
    STATUS_RUNNING_LABEL = os.getenv("STATUS_RUNNING_LABEL", "status:devin-running")
    STATUS_NEEDS_REVIEW_LABEL = os.getenv("STATUS_NEEDS_REVIEW_LABEL", "status:devin-needs-human-review")
    STATUS_COMPLETED_LABEL = os.getenv("STATUS_COMPLETED_LABEL", "status:devin-completed")
    STATUS_FAILED_LABEL = os.getenv("STATUS_FAILED_LABEL", "status:devin-failed")
    STORE_PATH = os.getenv("STORE_PATH", "./data/sessions.json")
    
    # Human baseline configuration (hours)
    HUMAN_BASELINE_QUALITY_HOURS = float(os.getenv("HUMAN_BASELINE_QUALITY_HOURS", "3"))
    HUMAN_BASELINE_SECURITY_HOURS = float(os.getenv("HUMAN_BASELINE_SECURITY_HOURS", "10"))
    HUMAN_BASELINE_OTHER_HOURS = float(os.getenv("HUMAN_BASELINE_OTHER_HOURS", "6"))
    
    # ROI configuration
    BLENDED_ENGINEERING_HOURLY_COST = float(os.getenv("BLENDED_ENGINEERING_HOURLY_COST", "150"))
    ROI_CURRENCY = os.getenv("ROI_CURRENCY", "A$")
    
    # Organization playbook configuration
    DEVIN_DEFAULT_PLAYBOOK_ID = os.getenv("DEVIN_DEFAULT_PLAYBOOK_ID")
    DEVIN_QUALITY_PLAYBOOK_ID = os.getenv("DEVIN_QUALITY_PLAYBOOK_ID")
    DEVIN_SECURITY_PLAYBOOK_ID = os.getenv("DEVIN_SECURITY_PLAYBOOK_ID")
    
    # Validate required environment variables
    if not DEVIN_API_KEY:
        logger.warning("DEVIN_API_KEY not set - Devin integration will not work. Set this environment variable to enable Devin session creation.")
    if not DEVIN_ORG_ID:
        logger.warning("DEVIN_ORG_ID not set - Devin integration will not work. Set this environment variable to enable Devin session creation.")
    if not GITHUB_TOKEN:
        logger.warning("GITHUB_TOKEN not set - GitHub API integration will not work. Set this environment variable to enable GitHub issue comments and label management.")
    
    return {
        "DEVIN_API_KEY": DEVIN_API_KEY,
        "DEVIN_ORG_ID": DEVIN_ORG_ID,
        "DEVIN_ORG_SLUG": DEVIN_ORG_SLUG,
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "DEFAULT_GITHUB_OWNER": DEFAULT_GITHUB_OWNER,
        "DEFAULT_GITHUB_REPO": DEFAULT_GITHUB_REPO,
        "TRIGGER_LABEL": TRIGGER_LABEL,
        "STATUS_RUNNING_LABEL": STATUS_RUNNING_LABEL,
        "STATUS_NEEDS_REVIEW_LABEL": STATUS_NEEDS_REVIEW_LABEL,
        "STATUS_COMPLETED_LABEL": STATUS_COMPLETED_LABEL,
        "STATUS_FAILED_LABEL": STATUS_FAILED_LABEL,
        "STORE_PATH": STORE_PATH,
        "HUMAN_BASELINE_QUALITY_HOURS": HUMAN_BASELINE_QUALITY_HOURS,
        "HUMAN_BASELINE_SECURITY_HOURS": HUMAN_BASELINE_SECURITY_HOURS,
        "HUMAN_BASELINE_OTHER_HOURS": HUMAN_BASELINE_OTHER_HOURS,
        "BLENDED_ENGINEERING_HOURLY_COST": BLENDED_ENGINEERING_HOURLY_COST,
        "ROI_CURRENCY": ROI_CURRENCY,
        "DEVIN_DEFAULT_PLAYBOOK_ID": DEVIN_DEFAULT_PLAYBOOK_ID,
        "DEVIN_QUALITY_PLAYBOOK_ID": DEVIN_QUALITY_PLAYBOOK_ID,
        "DEVIN_SECURITY_PLAYBOOK_ID": DEVIN_SECURITY_PLAYBOOK_ID
    }


def initialize_components(config: dict):
    """Initialize application components based on configuration."""
    store = SessionStore(config["STORE_PATH"])
    devin_client = DevinClient(config["DEVIN_API_KEY"], config["DEVIN_ORG_ID"]) if config["DEVIN_API_KEY"] and config["DEVIN_ORG_ID"] else None
    github_client = GitHubClient(config["GITHUB_TOKEN"]) if config["GITHUB_TOKEN"] else None
    
    return {
        "store": store,
        "devin_client": devin_client,
        "github_client": github_client
    }
