import os
import httpx
import logging
from typing import Dict, Any, Optional
from app.models import GitHubIssue

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

    def generate_prompt(self, issue: GitHubIssue, risk_labels: list[str]) -> str:
        """Generate a remediation prompt for Devin based on the issue and risk labels."""
        
        risk_context = ""
        if "risk:security" in risk_labels:
            risk_context = """
This issue is marked as a SECURITY risk. Focus on:
- Dependency vulnerabilities and security updates
- Security best practices and hardening
- Vulnerability remediation
- Security-focused validation and testing
"""
        elif "risk:quality" in risk_labels:
            risk_context = """
This issue is marked as a QUALITY risk. Focus on:
- Code quality improvements
- Maintainability and readability
- Linting and static analysis fixes
- Code style and consistency
"""
        else:
            risk_context = """
This issue is a general remediation request. Focus on:
- The specific issue described
- Safe, minimal changes
- Maintaining code quality
"""
        
        prompt = f"""You are an autonomous software engineering agent tasked with remediating a GitHub issue.

# Target Repository
- Owner: {issue.owner}
- Repository: {issue.repo}
- GitHub URL: https://github.com/{issue.owner}/{issue.repo}

# Issue Details
- Issue Number: {issue.number}
- Title: {issue.title}
- Description:
{issue.body}

- Issue URL: {issue.url}

# Risk Context
{risk_context}

# Your Task
1. Inspect the target GitHub repository to understand the codebase structure
2. Read and understand the GitHub issue thoroughly
3. Perform the smallest safe remediation aligned to the issue
4. Run relevant validation checks where practical (tests, linting, etc.)
5. Open a pull request against the target repository with your changes
6. Comment on the GitHub issue with:
   - A summary of the changes made
   - The pull request URL
   - Validation results

# Important Constraints
- Make minimal, focused changes
- Ensure all changes are safe and well-tested
- Follow the repository's existing code style and patterns
- If the issue is unclear or requires human judgment, add a comment explaining what you found
- Do not make destructive changes without clear justification

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

    async def create_session(self, prompt: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new Devin session with the given prompt."""
        
        session_url = f"{self.base_url}/v3/organizations/{self.org_id}/sessions"
        
        payload = {
            "prompt": prompt,
            "metadata": metadata
        }
        
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
