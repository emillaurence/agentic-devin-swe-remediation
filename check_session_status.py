import asyncio
import os
from dotenv import load_dotenv
from app.devin_client import DevinClient

# Load environment variables
load_dotenv()

async def check_session_status(session_id: str):
    """Check the status of a Devin session."""
    api_key = os.getenv("DEVIN_API_KEY")
    org_id = os.getenv("DEVIN_ORG_ID")
    
    if not api_key or not org_id:
        print("Error: DEVIN_API_KEY and DEVIN_ORG_ID must be set in .env file")
        return
    
    client = DevinClient(api_key, org_id)
    
    try:
        print(f"Checking status for session: {session_id}")
        status = await client.get_session_status(session_id)
        
        print("\nSession Status:")
        print(f"Status: {status.get('status')}")
        print(f"Pull Requests: {status.get('pull_requests')}")
        print(f"Pull Request URL: {status.get('pull_request_url')}")
        print(f"Error Message: {status.get('error_message')}")
        print(f"Validation Summary: {status.get('validation_summary')}")
        
        # Determine if done
        devin_state = status.get("status", "").lower()
        has_pull_requests = status.get("pull_requests") and len(status.get("pull_requests", [])) > 0
        terminal_states = ["completed", "failed", "suspended", "error"]
        
        is_done = devin_state in terminal_states or has_pull_requests
        
        print(f"\nTask Done: {is_done}")
        if is_done:
            print(f"Reason: {'Terminal state' if devin_state in terminal_states else 'Has pull requests'}")
        
    except Exception as e:
        print(f"Error checking session status: {str(e)}")

if __name__ == "__main__":
    session_id = "105e46b5a1244e64b820591b308c72a2"
    asyncio.run(check_session_status(session_id))
