# PLAN.md

> Committed before reading CLARIFICATIONS.md or writing any code. This is the plan.

## Architecture

One pipeline, each company handled on its own. Six stages:

1. **Ingest & normalize** — read the CSV, clean the company name (drop legal suffixes, fix casing), parse the mailing address into a canonical key. Garbage in is garbage everywhere, so this goes first.
2. **Fan out to providers** — hit several enrichment sources through one common interface, so the mocked providers and real ones are interchangeable. Cheap, deterministic sources first; stop early once I have enough agreement to be confident.
3. **Collect candidates** — each provider returns 0..n possible contacts. Every candidate carries its raw evidence and which provider it came from, from the first step. Provenance isn't something I bolt on at the end — nothing exists in this system without a source.
4. **Resolve / dedupe / merge** — cluster the candidates. Sources that agree reinforce a contact; sources that disagree become ranked alternatives, not a coin flip.
5. **Score & gate** — 0-100 confidence per contact, checked against a threshold to set `needs_human_review`.
6. **Emit** — one row per input: best contact (or none), role, contact value, confidence, source(s), `needs_human_review`, and a reason whenever I couldn't verify.

"Not found" and "not sure" are real outputs here, not failures. The pipeline is idempotent, rate-limited, and cached per (company, provider) so re-runs are cheap.

## Sources & strategy

No single source covers small businesses well, and the strongest confidence signal I have is two independent sources agreeing. So I combine source *types* that fail in different ways:

- **Official registries** (Secretary of State / business filings) — owner and officer names. Authoritative, but often stale.
- **The company's own website / contact page** — role, sometimes a direct line. Cheap, but messy and ambiguous.
- **Licensed B2B enrichment APIs** — role-tagged contacts, decent coverage. Trust, but verify — these can be confidently wrong.
- **Email-pattern inference + a deliverability check** — last resort only. Always capped to low confidence and flagged. A guessed email is never allowed to look "verified."

Order is cheap/deterministic → paid → inference, and I stop as soon as I get corroboration. Because these fail differently, *agreement across types* is what earns a high score — not any one source shouting loudly.

## Quality

- **Dedupe:** canonicalize name / email / phone / company, then cluster on (person + company) and on the contact value itself. Agreeing candidates merge; genuinely different ones stay as ranked alternatives.
- **Confidence (0-100):** built from (1) how many *independent* sources corroborate, (2) how much I trust each source, (3) whether the role actually matches the decision-maker I want, (4) whether the contact verified (email deliverable, phone valid), (5) how recent it is. Agreement pushes it up; a single source or an inferred guess gets capped. Documented bands — roughly 85+ I'll stand behind, 60–84 goes to a human, under 60 I don't return as confident.
- **Provenance:** every value I emit points back to its source(s) and a piece of raw evidence. I've been burned before by a "source" column that lied because one code path forgot to set it — so here, no source, no value.
- **Cannot-verify:** explicit and first-class. If nothing clears the bar, I return the best candidate with `needs_human_review=true` and a reason, or I return nothing. I do not invent a contact to fill a row. "I couldn't verify this" is a useful answer, not a failure.
- **False positives:** this is the failure that actually costs money. Emailing the wrong person at a Fortune 500 client about their debt is a brand and legal problem; a missing contact just lands on someone's desk. So I bias hard toward precision — conflicting or inference-only contacts get downgraded and flagged. A precise-looking email I can't back up is a red flag, not a win.
- **Knowing it actually works:** I'd hold out a small sample I can verify by hand and track *precision over coverage* — of the contacts I return, how many are right. Precision is the number that matters here; "% of rows we found someone for" is a vanity metric if a chunk of them are wrong. The two health signals I'd actually watch are the false-positive rate and how big the human-review queue gets.

## Privacy / compliance

- **Will:** use public / official / licensed *business* data for a legitimate B2B purpose, target *role-based* business contacts (owner, AP, CFO), respect robots.txt and ToS, keep full provenance so any decision is auditable, and keep only what I need to reach the right person.
- **Won't:** scrape personal or consumer data, go after home addresses or personal emails, bypass logins/paywalls/ToS, or send a guessed personal email I haven't verified.
- Debt collection is regulated — FDCPA in the US (real limits on contacting third parties and on disclosure) and GDPR in the EU (need a lawful basis). Jurisdiction is an input that gates behavior, not a footnote.

## Clarifying questions

Three that would actually change what I build — not fifteen to look thorough.

1. **How bad is a *wrong* contact versus *no* contact?**
   - Why it matters: in collections, reaching the wrong person is a brand/legal incident; a miss just routes to a human. That one ratio sets my confidence threshold and the whole precision-vs-coverage call.
   - Default if you never answer: I assume false positives are far more expensive — precision-biased, threshold around 70, and I never ship an inference-only contact as confident.
   - What changes with your answer: the threshold, whether I return low-confidence guesses at all, and how hard I lean on inference.

2. **Which sources are fair game — and can I use *verified* email-pattern inference, or only contacts pulled directly from a source?**
   - Why it matters: this defines the legal/allowed provider set and the ceiling on how confident inferred data is allowed to be. FDCPA/GDPR might rule some sources out entirely.
   - Default if you never answer: licensed B2B + official registries + company websites only. Inference allowed but capped and flagged. No personal data.
   - What changes with your answer: the provider list, the max confidence an inferred contact can reach, and how I handle different jurisdictions.

3. **Who counts as the "right" decision-maker — and do you want one best contact or a ranked shortlist?**
   - Why it matters: it drives role-match scoring and the shape of the output. Chasing an "owner" pulls different sources than chasing an "AP manager."
   - Default if you never answer: owner → CFO → AP / office manager for small businesses, and I return one best contact plus any high-confidence alternatives.
   - What changes with your answer: source weighting, how I score role matches, and whether the output is a single contact or a ranked list.
