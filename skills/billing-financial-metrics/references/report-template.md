# Cost Report Template

Use this layout for cost answers. Replace every `{placeholder}` with values
returned by the tools. Drop sections that do not apply.

```
Summary: {one-sentence answer to the question}

Total cost ({month}): ${total}
Previous month ({previous_month}): ${previous_total}
Change: {+/-}${change_amount} ({+/-}{change_pct}%)

Cost by service
| Service | Cost | Share | Change vs last month |
|---|---|---|---|
| {service} | ${cost} | {share}% | {+/-}${change} ({+/-}{pct}%) |

Main cost drivers
1. {service}: {+/-}${change} ({+/-}{pct}%) - {likely cause, from the service skill}

Savings opportunities (estimates)
| Opportunity | Est. saving / month | % of service | % of total bill |
|---|---|---|---|
| {title} | ${saving} | {pct}% | {pct}% |
Assumptions: {assumptions from the tool}

Not covered: {services without detailed data}

Next steps (for human approval): {recommendations}
```
