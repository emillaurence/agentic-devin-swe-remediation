import os
import httpx
import logging
from typing import Dict, Any, Optional
from app.core.models import GitHubIssue

logger = logging.getLogger(__name__)


class DevinClient:
    def __init__(self, api_key: Optional[str] = None, org_id: Optional[str] = None, base_url: str = "https://api.devin.ai"):
        self.api_key = api_key or os.getenv("DEVIN_API_KEY")
        self.org_id = org_id or os.getenv("DEVIN_ORG_ID")
        self.base_url = base_url.rstrip('/')
        
        if not self.api_key:
            raise ValueError("DEVIN_API_KEY is required")
        if not self.org_id:
            raise ValueError("DEVIN_ORG_ID is required")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate_prompt(self, issue: GitHubIssue, risk_labels: list[str], playbook_type: Optional[str] = None) -> str:
        """Generate a remediation prompt for Devin based on the issue and risk labels."""
        
        # Task classification based on risk labels
        work_type = "General remediation"
        guidance = "Focus on the specific issue description. Make the smallest safe change that produces a reviewable pull request."
        
        if "risk:security" in risk_labels:
            work_type = "Security remediation"
            guidance = "Focus on the security concern described in the issue. Prefer the smallest safe remediation, avoid broad dependency upgrades, and clearly document security impact and residual risk."
        elif "risk:quality" in risk_labels:
            work_type = "Quality remediation"
            guidance = "Focus on code quality, maintainability, tests, linting, static analysis, or small cleanup. Preserve existing behavior and avoid broad refactors."
        
        # Playbook context based on playbook_type
        playbook_context = ""
        if playbook_type == "security":
            playbook_context = "Use the selected organization security remediation playbook as the general procedure."
        elif playbook_type == "quality":
            playbook_context = "Use the selected organization quality remediation playbook as the general procedure."
        elif playbook_type == "default":
            playbook_context = "Use the selected organization default remediation playbook as the general procedure."
        else:
            playbook_context = "No organization playbook is configured. Follow the issue-specific remediation contract below."
        
        playbook_context += "\nThe playbook provides the general workflow. The GitHub Issue below is the source of truth for this specific remediation."
        
        # Format labels for display
        all_labels = [label.name for label in issue.labels]
        labels_str = ", ".join(all_labels) if all_labels else "None"
        risk_labels_str = ", ".join(risk_labels) if risk_labels else "None"
        
        prompt = f"""# Role and Objective
You are an autonomous software engineering agent tasked with remediating a GitHub issue. Your objective is to produce a small, isolated, independently reviewable remediation that addresses the issue.

# Selected Playbook Context
{playbook_context}

# Target Repository
- Owner: {issue.owner}
- Repository: {issue.repo}
- GitHub URL: https://github.com/{issue.owner}/{issue.repo}

# GitHub Issue Details
- Issue Number: {issue.number}
- Title: {issue.title}
- Description:
{issue.body}
- Issue URL: {issue.url}

# Labels and Risk Labels
- All Labels: {labels_str}
- Risk Labels: {risk_labels_str}

# Task Classification
- Work Type: {work_type}
- Guidance: {guidance}

# Scope Boundaries
- Make the smallest safe change that addresses the issue.
- Treat this as one isolated remediation slice.
- Do not perform broad refactors.
- Do not fix unrelated issues.
- Do not update unrelated dependencies.
- Do not change public behavior unless required by the issue.
- Prefer a focused one-file or small multi-file change.
- Follow existing repository style, conventions, and patterns.
- Avoid speculative improvements.

# Execution Plan
1. Read the GitHub Issue carefully.
2. Inspect only the relevant parts of the repository.
3. Identify the smallest safe remediation.
4. Implement the change on a branch.
5. Run the smallest relevant validation where practical.
6. Open a pull request against the target repository.
7. Comment on the GitHub Issue with the PR URL, remediation summary, and validation result.
8. Stop after opening the PR and commenting on the issue.

# Validation Guidance
- If Python code changes, run the most targeted available test, lint, or type check where practical.
- If frontend code changes, run the most targeted test, lint, type check, or build check where practical.
- If dependency or security files change, run package manager, lockfile, dependency, test, or build validation where practical.
- If documentation-only changes are made, state that automated validation is not applicable.
- If validation cannot be run due to environment or time constraints, explain why in the PR and issue comment.

# Pull Request Requirements
The PR description must include:
- Linked GitHub Issue
- Summary of the change
- Files changed
- Validation performed
- Risks, residual risk, or follow-up required

# GitHub Issue Comment Requirements
After opening the PR, comment on the original GitHub Issue with:
- PR URL
- Summary of remediation
- Validation result
- Final status: ready for human review

# Blocker Handling
If you cannot safely create a PR, you must comment on the GitHub Issue with:
- Blocker encountered
- Steps attempted
- Information, access, or decision needed
- Recommended next action

# Stop Condition
- Stop after opening the pull request and commenting on the GitHub Issue.
- Do not merge the pull request.
- Human review remains the merge gate.

Begin your work now.
"""
        return prompt

    async def check_authentication(self) -> Dict[str, Any]:
        """Check Devin API authentication by calling GET /v3/self.
        
        Returns:
            Dict containing authentication status and user info (service user name, org ID)
        
        Raises:
            ValueError: If authentication fails (401) or other errors occur
        """
        auth_url = f"{self.base_url}/v3/self"
        
        logger.info("Checking Devin API authentication")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    auth_url,
                    headers=self.headers
                )
                
                # Handle 401 Unauthorized specifically
                if response.status_code == 401:
                    error_msg = "Devin API authentication failed (401 Unauthorized). Please check DEVIN_API_KEY."
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                response.raise_for_status()
                result = response.json()
                logger.info(f"Devin authentication successful: {result.get('principal_type')}")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error checking Devin authentication: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error checking Devin authentication: {str(e)}")
            raise

    async def create_session(self, prompt: str, metadata: Dict[str, Any], playbook_id: Optional[str] = None, issue: Optional[GitHubIssue] = None, risk_labels: Optional[list[str]] = None) -> Dict[str, Any]:
        """Create a new Devin session with the given prompt."""
        
        session_url = f"{self.base_url}/v3/organizations/{self.org_id}/sessions"
        
        payload = {
            "prompt": prompt,
            "metadata": metadata
        }
        
        # Include playbook_id if provided
        if playbook_id:
            payload["playbook_id"] = playbook_id
        
        # Add title and tags if issue is provided
        if issue:
            payload["title"] = f"Remediate {issue.repo} issue #{issue.number}"
            tags = ["devin-remediate"]
            if risk_labels:
                tags.extend(risk_labels)
            payload["tags"] = tags
        
        logger.info(f"Creating Devin session with metadata: {metadata}")
        
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    session_url,
                    headers=self.headers,
                    json=payload
                )
                
                # Handle 401 Unauthorized specifically
                if response.status_code == 401:
                    error_msg = "Devin API authentication failed (401 Unauthorized). Please check DEVIN_API_KEY."
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                response.raise_for_status()
                result = response.json()
                logger.info(f"Devin session created: {result.get('session_id')}")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error creating Devin session: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error creating Devin session: {str(e)}")
            raise

    async def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get the status of a Devin session."""
        
        session_url = f"{self.base_url}/sessions/{session_id}"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    session_url,
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error getting Devin session status: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error getting Devin session status: {str(e)}")
            raise

    async def cancel_session(self, session_id: str) -> Dict[str, Any]:
        """Cancel a Devin session."""
        
        session_url = f"{self.base_url}/sessions/{session_id}/cancel"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    session_url,
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error canceling Devin session: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error canceling Devin session: {str(e)}")
            raise
