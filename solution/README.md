# Contact Finder — slice

Takes the company CSV, cross-references three (mocked) sources, and returns one
decision-maker contact per company — or an honest `needs_human_review` when it
can't verify one.

## Run
```bash
cd solution
python3 find_contacts.py        # defaults to the challenge CSV + mocks
```
Writes `output.csv` (the required columns) and `output.json` (same rows + provenance
+ the reasons behind each score), and prints a summary table.

## How it adapts to CLARIFICATIONS.md
My `PLAN.md` was committed before I read the clarifications. Three things changed in the build because of them:

1. **Persona order flipped.** The plan had `owner → CFO → AP`. The clarifications say **AP / accounts-payable first**, so `PERSONA_PRIORITY` leads with AP. (None of the mock rows actually expose an AP role, but the ordering is in place for when one does.)
2. **Threshold pinned to 70.** `confidence < 70` → the contact value is withheld (`""`) and `needs_human_review = true`. No guessing across that line.
3. **Precision over recall, explicitly.** A high review rate on hard rows is the goal, not a miss — so conflicts, lone weak guesses, and "no name" rows are sent to a human instead of forced into a confident-looking answer.

## Confidence model (explainable on purpose)
Confidence is driven by **independent corroboration**, not any single source shouting:

| Signal | Effect |
|---|---|
| A real person identified | +40 |
| A second independent source agrees | +22 |
| 2+ independent agreements | +16 |
| Contact value attributable to that person | +6 |
| Role is a real decision-maker | +5 |
| Contact is a generic inbox (`info@`, `office@`) | −18 |
| Role is "Registered Agent" (not a decision-maker) | −30 |
| Sources name *different* people (conflict) | hard-capped at 25 |
| Corroborated phone but nobody named | capped at 60 |
| No source returned anything | 0 |

Top score is ~89, not 100 — even when everything agrees, a mocked dataset doesn't earn certainty.

## How the hard rows are handled
- **Conflict** (Coastal Breeze: registry "Tina Alvarez" vs listing "Marcus Webb") → 30, review. Two sources naming different people is *less* trustworthy than one, not more.
- **Wrong role** (Northgate: "Registered Agent") → 10, review. A legal proxy isn't who we collect from.
- **Phone, no name** (Sunbelt: two sources agree on a phone, nobody named) → 60, review. We know the number, not the person.
- **Single weak guess** (Riverside `info@`, conf 41) → 22, review.
- **No data** (12 companies) → 0, review. "Cannot verify" is a valid answer.

## Provenance
Every contact in `output.json` carries the `source_url`s it came from. A contact is
never emitted unless it traces to at least one source — no source, no value.

## Structure
- `providers.py` — the three sources behind one interface (swap the mock for a real client, pipeline unchanged).
- `find_contacts.py` — normalize → cross-reference → score → gate on the threshold → emit with provenance.
