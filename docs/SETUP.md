# Setup Guide

Complete step-by-step guide to set up and run the agentic remediation workflow.

## Prerequisites

- Python 3.11 or higher
- Devin API key and organization ID
- GitHub personal access token with repo permissions
- ngrok account (for local webhook testing)
- A GitHub repository to remediate issues in

## Step 1: Configure GitHub Repository Labels

Before running the application, set up the required labels in your GitHub repository:

1. Go to your GitHub repository
2. Navigate to **Settings** → **Labels**
3. Create the following labels:

**Trigger Label:**
- `devin-remediate` - Add this to issues to trigger Devin remediation

**Risk/Category Labels:**
- `risk:security` - For security-focused remediation (dependencies, vulnerabilities)
- `risk:quality` - For quality-focused remediation (code quality, linting, static analysis)

**Status Labels:**
- `status:devin-running` - Automatically added when Devin starts (optional, system will create)
- `status:devin-needs-human-review` - Added when Devin completes and opens PR (optional, system will create)
- `status:devin-completed` - Added when remediation is approved (optional, system will create)
- `status:devin-failed` - Added when remediation fails (optional, system will create)

**Note:** The system will automatically create status labels if they don't exist, but creating them beforehand ensures consistency.

## Step 2: Set Up Environment Variables

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit `.env` and fill in the required values:

```bash
# Devin API Configuration
DEVIN_API_KEY=your_actual_devin_api_key
DEVIN_ORG_ID=your_actual_devin_org_id

# GitHub API Configuration
GITHUB_TOKEN=your_actual_github_token

# Default GitHub Repository (update to your target repo)
DEFAULT_GITHUB_OWNER=your_github_username
DEFAULT_GITHUB_REPO=your_target_repository

# Ngrok Configuration (required for Docker Compose webhook support)
NGROK_AUTHTOKEN=your_ngrok_authtoken
```

**Getting your credentials:**

- **Devin API Key & Org ID**: Log in to https://app.devin.ai and get these from your account settings
- **GitHub Token**: Create a personal access token at https://github.com/settings/tokens with `repo` permissions
- **Ngrok Auth Token**: Sign up at https://ngrok.com and get your authtoken from the dashboard

## Step 3: Start the Application with Docker Compose (Recommended)

Docker Compose is the recommended way to run the application:

1. Build and run with Docker Compose:

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`

2. Verify it's running:

```bash
curl http://localhost:8000/health
```

You should see a response indicating the service is healthy.

3. To stop the application:

```bash
docker compose down
```

**Alternative: Manual Python Execution**

If you prefer to run the application manually without Docker:

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the FastAPI application:

```bash
python -m app.main
```

The API will be available at `http://localhost:8000`

## Step 4: Test Devin Authentication

Verify your Devin credentials are configured correctly:

```bash
curl http://localhost:8000/health/devin
```

Expected response:
```json
{
  "status": "authenticated",
  "principal_type": "service user",
  "service_user_name": "your-service-user",
  "org_id": "your-org-id"
}
```

## Step 5: Set Up ngrok for Local Webhook Testing

To receive GitHub webhooks locally, you need to expose your local server to the internet.

**Using Docker Compose (Automatic):**

ngrok is automatically configured when using Docker Compose. Just ensure you've added your ngrok authtoken to the `.env` file:

```bash
NGROK_AUTHTOKEN=your_ngrok_authtoken
```

When you run `docker compose up --build`, ngrok will automatically start and tunnel the app service. You'll see the ngrok URL in the docker compose logs.

**Alternative: Manual ngrok Setup**

If you're running the application manually without Docker Compose:

1. Install ngrok (if not already installed):
   ```bash
   # macOS
   brew install ngrok

   # Or download from https://ngrok.com
   ```

2. Authenticate ngrok (optional, but recommended for persistent URLs):
   ```bash
   ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN
   ```

3. Start ngrok to tunnel port 8000:
   ```bash
   ngrok http 8000
   ```

4. Copy the ngrok HTTPS URL (e.g., `https://abc123.ngrok.io`)

**Keep ngrok running** in a separate terminal window while testing.

## Step 6: Configure GitHub Webhooks

1. Go to your GitHub repository
2. Navigate to **Settings** → **Webhooks** → **Add webhook**
3. Configure the webhook:

**Payload URL:**
```
https://your-ngrok-url.ngrok.io/webhook/github/issue
```

**Content type:** `application/json`

**Secret:** (Optional) Create a secret and add `GITHUB_WEBHOOK_SECRET=your_secret` to your `.env` file

**Events:** Select only "Issues" (do not select "Pull requests" for this webhook)

**Active:** Check the box to enable the webhook

4. Click "Add webhook"

5. For automated PR completion, add a second webhook:
   - **Payload URL:** `https://your-ngrok-url.ngrok.io/webhook/github/pull_request`
   - **Events:** Select "Pull requests"

## Step 7: Test the Complete Workflow

Now test the end-to-end workflow:

1. **Create a test issue** in your GitHub repository with:
   - Title: "Test Devin remediation"
   - Description: "This is a test issue for the remediation workflow"
   - Labels: `devin-remediate` and `risk:quality` (or `risk:security`)

2. **Watch the logs** in your terminal where the app is running. You should see:
   - Webhook received
   - Devin session created
   - Status labels updated on GitHub

3. **Monitor progress**:
   - Check the dashboard: `http://localhost:8000/dashboard`
   - Check session status: `http://localhost:8000/sessions`
   - Check metrics: `http://localhost:8000/metrics`

4. **Verify GitHub updates**:
   - The issue should have `status:devin-running` label
   - A comment should be added indicating Devin is working
   - When Devin completes, a PR should be created
   - The issue should have `status:devin-needs-human-review` label

5. **Complete the workflow**:
   - Review the PR in GitHub
   - Merge the PR if satisfied
   - The system will automatically mark the session as completed
   - The issue should have `status:devin-completed` label

## Alternative: Test Without Webhooks (Simulation)

If you want to test without setting up webhooks, use the simulation endpoint:

```bash
python scripts/simulate_event.py \
  --owner your_github_username \
  --repo your_target_repository \
  --number 1 \
  --title "Test remediation" \
  --body "Test issue for remediation" \
  --labels devin-remediate risk:quality
```

This simulates a webhook event without requiring GitHub webhooks to be configured.

## Step 8: Monitor and Manage Sessions

**View all sessions:**
```bash
curl http://localhost:8000/sessions
```

**View sessions needing review:**
```bash
curl http://localhost:8000/sessions/review-queue
```

**Manually sync session status:**
```bash
curl -X POST http://localhost:8000/sessions/sync
```

**Manually mark a session as completed:**
```bash
curl -X POST http://localhost:8000/sessions/{session_id}/complete \
  -H "Content-Type: application/json" \
  -d '{"pull_request_url": "https://github.com/owner/repo/pull/123"}'
```

## Troubleshooting

**Webhook not triggering:**
- Check GitHub webhook delivery logs in Settings → Webhooks
- Verify ngrok is running and the URL is correct
- Check the application logs for errors

**Devin authentication failed:**
- Verify `DEVIN_API_KEY` and `DEVIN_ORG_ID` are correct
- Test with `curl http://localhost:8000/health/devin`

**GitHub API errors:**
- Verify `GITHUB_TOKEN` has proper `repo` permissions
- Check the token hasn't expired

**Session not updating:**
- Manually trigger sync: `curl -X POST http://localhost:8000/sessions/sync`
- Check the Devin session URL directly in the browser

## Production Deployment

For production use:

1. Deploy the application to a cloud provider (AWS, GCP, Azure, or Heroku)
2. Use environment variables for configuration (not `.env` file)
3. Configure GitHub webhooks to point to your production URL
4. Set up proper logging and monitoring
5. Consider using a database instead of local JSON storage for scalability

## Environment Variables Reference

Required environment variables:

- `DEVIN_API_KEY` - Your Devin API key
- `DEVIN_ORG_ID` - Your Devin organization ID
- `GITHUB_TOKEN` - GitHub personal access token with repo permissions

Optional environment variables (with defaults):

- `DEFAULT_GITHUB_OWNER=emillaurence` - Default repository owner
- `DEFAULT_GITHUB_REPO=superset` - Default repository name
- `TRIGGER_LABEL=devin-remediate` - Label that triggers remediation
- `STATUS_RUNNING_LABEL=status:devin-running` - Label for running sessions
- `STATUS_NEEDS_REVIEW_LABEL=status:devin-needs-human-review` - Label for sessions needing human review
- `STATUS_COMPLETED_LABEL=status:devin-completed` - Label for completed sessions
- `STATUS_FAILED_LABEL=status:devin-failed` - Label for failed sessions
- `STORE_PATH=./data/sessions.json` - Path to session storage file
- `BLENDED_ENGINEERING_HOURLY_COST=150` - Blended hourly cost for engineering time (default: 150)
- `ROI_CURRENCY=A$` - Currency symbol for ROI display (default: A$)
