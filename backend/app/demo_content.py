"""Pre-written slot drafts used by the offline demo and the opt-in UI demo mode (APP_DEMO=1).

Each entry is (text, [fact keys cited]). The text is deliberately faithful to the synthetic sample
evidence in ``samples/``; it stands in for what ``LLMDraftingModel`` would return from Azure OpenAI.
"""

DEMO_DRAFTS = {
    "circumstances_summary": [
        ("You are currently employed full time as a senior project manager.", ["client.employment_status"]),
        ("You have not told us about any circumstances that might make you vulnerable.",
         ["client.vulnerability_flag"]),
    ],
    "objectives_summary": [
        ("You told us that you would like to consolidate your old workplace pension into a plan you can "
         "manage online, and to reduce the charges you pay.", ["client.objectives"]),
        ("You intend to retire at 63.", ["client.retirement_age_target"]),
    ],
    "risk_summary": [
        ("Your attitude to risk is recorded as Balanced (4 out of 7).", ["client.attitude_to_risk"]),
        ("You told us that a fall in the value of this pension would not affect your standard of living, "
         "so your capacity for loss is recorded as high.", ["client.capacity_for_loss"]),
    ],
    "recommendation_explanation": [
        ("We recommend that you transfer your Northbridge Life pension, currently valued at £125,400.00, "
         "to the recommended personal pension.", ["adviser.recommendation", "pension.fund_value"]),
        ("This reduces your total annual charge from 1.15% to 0.55%, which supports your objective of "
         "reducing the charges you pay.",
         ["pension.annual_charge_pct", "adviser.recommended_charge_pct", "client.objectives"]),
        ("The plan can be managed online and offers a range of funds matched to a balanced attitude to "
         "risk.", ["adviser.reasons"]),
    ],
}
