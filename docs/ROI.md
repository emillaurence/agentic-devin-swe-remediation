# ROI Calculation

The dashboard calculates and displays **Estimated Engineering Cost Avoided** as the main hero metric in the Executive Overview. This represents the financial value of engineering time saved through agentic remediation.

## Calculation Method

Estimated Engineering Cost Avoided is calculated from actual time saved already tracked by the app:

```
Estimated Engineering Cost Avoided = actual_time_saved_hours × blended_engineering_hourly_cost
```

### Example

- Actual engineering time saved: 3.0 hrs
- Blended engineering hourly cost: A$150/hr
- Estimated Engineering Cost Avoided: A$450

## Configuration

The ROI calculation uses the following environment variables:

- `BLENDED_ENGINEERING_HOURLY_COST` - Blended hourly cost for engineering time (default: 150)
- `ROI_CURRENCY` - Currency symbol for ROI display (default: A$)

These can be overridden in your `.env` file to match your organization's cost structure and currency.

## Important Notes

- The value is calculated from actual or observed engineering time saved based on the remediation workflow timing already tracked by the app
- Sessions with "Needs Triage (Failed)" status are excluded from this calculation as they did not produce a productive PR
- This is for ROI modelling purposes only, not for billing
- The calculation uses the difference between human baseline hours and actual Devin execution time to determine actual time saved
