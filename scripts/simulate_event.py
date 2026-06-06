#!/usr/bin/env python3
"""
Script to simulate a remediation event without a live GitHub webhook.

This script allows local testing by sending a simulated issue to the /simulate endpoint.
"""

import os
import sys
import argparse
import httpx
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Simulate a remediation event")
    parser.add_argument(
        "--owner",
        default=os.getenv("DEFAULT_GITHUB_OWNER", "emillaurence"),
        help="GitHub repository owner"
    )
    parser.add_argument(
        "--repo",
        default=os.getenv("DEFAULT_GITHUB_REPO", "superset"),
        help="GitHub repository name"
    )
    parser.add_argument(
        "--number",
        type=int,
        default=1,
        help="GitHub issue number"
    )
    parser.add_argument(
        "--title",
        default="Test Devin remediation workflow",
        help="Issue title"
    )
    parser.add_argument(
        "--body",
        default="This is a test issue to validate the Devin remediation workflow.",
        help="Issue body/description"
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        default=["devin-remediate", "risk:quality"],
        help="Issue labels (space-separated)"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Issue URL (auto-generated if not provided)"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="API base URL"
    )
    
    args = parser.parse_args()
    
    # Generate URL if not provided
    if not args.url:
        args.url = f"https://github.com/{args.owner}/{args.repo}/issues/{args.number}"
    
    # Build request payload
    payload = {
        "owner": args.owner,
        "repo": args.repo,
        "number": args.number,
        "title": args.title,
        "body": args.body,
        "labels": args.labels,
        "url": args.url
    }
    
    print(f"Simulating remediation event:")
    print(f"  Repository: {args.owner}/{args.repo}")
    print(f"  Issue: #{args.number}")
    print(f"  Title: {args.title}")
    print(f"  Labels: {', '.join(args.labels)}")
    print(f"  URL: {args.url}")
    print()
    
    try:
        response = httpx.post(
            f"{args.api_url}/simulate",
            json=payload,
            timeout=30.0
        )
        response.raise_for_status()
        
        result = response.json()
        print(f"✓ Simulation accepted")
        print(f"  Status: {result['status']}")
        print(f"  Issue Number: {result['issue_number']}")
        print(f"  Risk Labels: {result.get('risk_labels', [])}")
        print(f"  Message: {result['message']}")
        
    except httpx.HTTPStatusError as e:
        print(f"✗ HTTP error: {e.response.status_code}")
        print(f"  Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
