import os
import httpx
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.base_url = "https://api.github.com"

    async def add_label(self, owner: str, repo: str, issue_number: int, label: str) -> Dict[str, Any]:
        """Add a label to a GitHub issue."""
        
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/labels"
        payload = {"labels": [label]}
        
        logger.info(f"Adding label '{label}' to {owner}/{repo}#{issue_number}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully added label '{label}'")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error adding label: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error adding label: {str(e)}")
            raise

    async def remove_label(self, owner: str, repo: str, issue_number: int, label: str) -> None:
        """Remove a label from a GitHub issue."""
        
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/labels/{label}"
        
        logger.info(f"Removing label '{label}' from {owner}/{repo}#{issue_number}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    url,
                    headers=self.headers
                )
                # 404 is acceptable if label doesn't exist
                if response.status_code != 404:
                    response.raise_for_status()
                logger.info(f"Successfully removed label '{label}'")
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                logger.error(f"HTTP error removing label: {e.response.status_code} - {e.response.text}")
                raise
        except Exception as e:
            logger.error(f"Error removing label: {str(e)}")
            raise

    async def add_comment(self, owner: str, repo: str, issue_number: int, body: str) -> Dict[str, Any]:
        """Add a comment to a GitHub issue."""
        
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        payload = {"body": body}
        
        logger.info(f"Adding comment to {owner}/{repo}#{issue_number}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully added comment")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error adding comment: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error adding comment: {str(e)}")
            raise

    async def get_issue(self, owner: str, repo: str, issue_number: int) -> Dict[str, Any]:
        """Get details of a GitHub issue."""
        
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}"
        
        logger.info(f"Getting issue {owner}/{repo}#{issue_number}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error getting issue: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error getting issue: {str(e)}")
            raise

    async def get_labels(self, owner: str, repo: str, issue_number: int) -> List[Dict[str, Any]]:
        """Get all labels for a GitHub issue."""
        
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/labels"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error getting labels: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error getting labels: {str(e)}")
            raise
