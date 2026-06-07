# Dashboard Documentation

The system includes an executive-friendly control tower dashboard providing operational visibility from engineering issue signal to autonomous remediation and pull request review.

## Access

Access the dashboard at:
- **Localhost**: `http://localhost:8000/dashboard`
- **ngrok**: `https://your-ngrok-url.ngrok.io/dashboard`

## Purpose

The dashboard is designed for engineering leadership and answers the question: "Is agentic remediation creating engineering leverage by converting issue signals into reviewable pull requests faster, with governance and traceability?"

## Tab 1: Executive Overview (Default)

### Value Statement
Explains the business impact of agentic remediation.

### Hero KPI
- **Estimated Engineering Cost Saved** - Financial value of engineering time saved through agentic remediation

### Headline KPI Cards (aligned to four business outcomes)
- **Productivity: Reviewable PRs Created** - Number of Devin remediation sessions that produced a pull request
- **Resilience: Risk Issues in Remediation** - Number of accepted remediation sessions with risk labels such as risk:security or risk:quality
- **Reliability: Issue-to-PR Conversion Rate** - Reviewable PRs created divided by accepted GitHub Issues processed
- **Governance: PRs Awaiting Review** - Sessions where Devin has produced a PR and human review is now required

### Operating Status Strip
- **Active Remediations** - Sessions where Devin is currently working and no PR has been created yet
- **Needs Triage (Failed)** - Sessions where Devin could not safely progress to a reviewable PR and needs engineer input
- **Mean Time to Reviewable PR** - Average time from session creation to PR detection, where available

### Operating Health Strip
Shows healthy if no items need triage, needs attention otherwise.

## Tab 2: Remediation Queue

Operational status view showing one row per issue/session.

### Columns
- Issue #
- Issue Title
- Repository
- Risk Category
- Devin Status
- PR Link
- Last Updated

### Status Mapping
- **Running** = Devin is actively working
- **Needs Human Review** = PR created, human review required
- **Completed** = Devin session fully completed
- **Needs Triage (Failed)** = Session failed and needs engineer input

## Tab 3: Risk and Value

Breakdown of remediation work by risk category.

### Categories
- risk:quality
- risk:security
- Unclassified

### For Each Category
- Cost Saved
- Time Saved
- Number of issues
- Number of PRs created
- Number awaiting review
- Number needing triage (failed)

### Executive Explanation
Shows where agentic remediation is being applied across different risk categories.

## Tab 4: Session Details

Detailed technical session information for senior ICs and technical reviewers.

### Columns
- Issue #
- Title
- Repository
- All Labels
- Risk Category
- Devin Status
- Devin Session (clickable link)
- PR Link (clickable link)
- Time to PR
- Error Message
- Created At
- Updated At

### Links
- Devin Session links to https://app.devin.ai/sessions/{session_id}
- PR links open in new tab

## Design Features

- Clean dark enterprise SaaS look aligned with Cognition/Devin
- Color palette: Primary blue (#3969CA), Accent blue (#0294DE), Success green (#21C19A), Deep navy background (#0B1020)
- Responsive desktop layout
- Clickable GitHub issue, Devin session, and PR links
- No heavy frontend framework - self-contained HTML/CSS/vanilla JavaScript
- Reads directly from local JSON session store
- Refresh the page to see the latest data

## Why These KPIs Matter to Engineering Leaders

### Productivity: Reviewable PRs Created
Measures actual output and engineering leverage created by Devin, showing that the agent is producing usable engineering output.

### Resilience: Risk Issues in Remediation
Shows how security and quality issues are being actively moved toward remediation before they accumulate into operational risk.

### Reliability: Issue-to-PR Conversion Rate
Indicates how effectively the system converts accepted GitHub Issues into reviewable pull requests, demonstrating workflow reliability.

### Governance: PRs Awaiting Review
Highlights where human attention is needed for governance, ensuring humans remain in control as the merge gate.

## Needs Triage (Failed)

This KPI tracks remediations where Devin could not safely progress to a reviewable PR and needs engineer input. These may include:
- Failed sessions due to errors or timeouts
- Suspended sessions requiring human input
- Blocked sessions that could not proceed
- Any state where Devin cannot safely continue or produce a reviewable PR

The underlying GitHub status label remains `status:devin-failed` for these sessions, but the dashboard uses the more descriptive "Needs Triage (Failed)" terminology to clearly communicate that human attention is needed.
