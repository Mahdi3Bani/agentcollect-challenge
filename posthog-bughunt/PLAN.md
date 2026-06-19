# PLAN.md — Auto-flagging UX bugs from PostHog session replays

> Plan-first, before any code. Goal: **flag** a UX bug from replays *before a user reports it* — flagging only, not fixing. Bias: precision over recall (alert fatigue is the enemy).

## Problem framing + separating surfaces

A UX bug here is almost never a crash. It's a **control that does nothing**, a **button clicked 5× in frustration**, a **page abandoned mid-task**. So I don't model "errors." I model the **gap between expressed intent and system response**: the user told the product they wanted something (clicked, typed, selected), and the product didn't do the expected thing. That gap is the bug, independent of which feature it lives in.

AgentCollect has **two surfaces that fail differently and cost differently** — so they get separate baselines, thresholds, and severity, never one shared model:

- **Debtor pages (payment, dispute).** One-shot, anonymous, short sessions, high abandonment is *normal*. Success = money moved or dispute filed. A dead control here is **lost revenue + a debtor who never comes back** (no retry, no support ticket — they just leave, so we'll *never* hear about it: this surface is exactly where pre-emptive flagging earns its keep). Real PII. Stakes: highest.
- **Client dashboard (case mgmt, imports, reports).** Power users, long repeat sessions, identifiable, tolerant of friction. Success = report rendered / import completed / case actioned. A bug is recoverable (they'll retry or file a ticket) but **compounds across every case they touch**. Business data, not consumer PII.

Why separate: the *same raw signal means different things*. 5 clicks + abandon on a debtor payment button is a SEV1 revenue incident; the same on a dashboard filter is a SEV3 annoyance. Different success events, different "normal" abandonment rates, different privacy posture. Mixing them destroys both precision and severity.

## The signal model & why it generalizes to unforeseen bugs

The hard gate is **generalization** — catching bugs we've never seen, on traces we've never seen, with no hardcoded list. I get there by modelling **intent-agnostic futility primitives** instead of named bugs. Each primitive = *an intent signal* ⊕ *the absence of the consequence that intent should produce*. A never-before-seen bug still produces one of these shapes, because they're the **physics of a broken interaction**, not a symptom catalog:

1. **Effortful no-op** — the same element (same DOM target) is acted on repeatedly with **no resulting state change**. State change = a following `$autocapture` with changed element *state*, a navigation (`$pageview`/route change), a network success, or DOM mutation. Subsumes `$rageclick` but is broader: "action without consequence." *5 clicks on a stepper that increments = fine. 5 clicks on a disabled submit = futile.*
2. **Interaction-then-abandon** — user interacted *meaningfully* (typed/selected/clicked) and then `$pageleave` **without reaching the surface goal**. The interaction proves intent; the abandon proves the goal wasn't met. This is what separates "bounced cold" (maybe wrong audience, not a bug) from "engaged, then gave up" (smells like a blocker).
3. **Navigation dead-end / oscillation** — reaches a state with no forward path, or loops A→B→A→B in the funnel (can't find or can't complete the next step).
4. **Blocked-state persistence** — element sits in a terminal-blocking state (disabled, validation error showing, spinner that never resolves) *while the user keeps trying*. Uses element **state** from autocapture.
5. **Latency futility** — interaction → long gap → repeat-or-abandon (loading that never lands; a soft failure that looks like a dead control).

**Why this generalizes:** every primitive is parameterized by `(surface, page, element)` and defined purely as *intent without expected effect* — so it fires on a feature shipped tomorrow exactly as on one shipped last year. We're modelling the gap, not the feature.

**Designed across signals — never dependent on the flaky ones.** `$exception` and `$dead_click` are *not* reliably captured, so they are **corroborating boosters only, never triggers**. Every primitive is computable from the reliable core — `$autocapture` (+ element state), `$rageclick`, `$pageleave`, `$pageview` — so any one signal missing doesn't blind the detector. (`$rageclick` is itself a PostHog heuristic over autocapture, so even it can be reconstructed if it drifts.)

## How I decide broken-vs-intended (the expected-behaviour ground truth)

This is the whole game, and where precision is won. **A raw signal is never a flag.** Every candidate is anchored to an **expected-behaviour source of truth**, layered cheapest→strongest:

1. **Did the action cause an effect? (local truth — the key discriminator.)** For the *same element in the same session*: did the action produce a state change / DOM mutation / network success / navigation within N ms? No effect → candidate. Per-element, self-calibrating, zero config.
2. **Did the session reach its goal? (session truth.)** Per-surface goal event (payment confirmed, dispute submitted, report rendered, import completed). Frustration on a session that *still succeeded* = low severity (user pushed through). Frustration ending in non-goal abandon = high.
3. **Peer comparison on the same element (population truth — the anti-false-positive workhorse.)** For element E on page P, what fraction of sessions that touch E get an effect / proceed? A stepper "doing nothing visible" still has ~99% of peers proceeding → won't flag. A genuinely dead button diverges from *its own* peer baseline → flags. This also catches **new** bugs automatically: a deploy breaks E, its effect-rate craters vs its own 7-day baseline.
4. **Happy-path funnel deviation (flow truth.)** Canonical funnel per surface (debtor: land → amount → review → pay → confirm). A session that stalls at a step peers pass = candidate, localized to that step.

**The discriminator in one line:** 5 clicks on a *stepper* passes #1 (each click changes state) and #3 (peers also multi-click and proceed) → no flag. 5 clicks on a *disabled submit* fails #1 (no state change), fails #2 (no payment), diverges on #3 (peers who click submit proceed) → high-confidence flag.

**Precision mechanisms:**
- **Require ≥2 independent truths to disagree** before alerting (e.g. no-effect *and* goal-not-reached, or no-effect *and* peer-divergence). A single truth = watchlist, not page.
- **Baseline warm-up:** never flag an element until it has a stable peer baseline — otherwise every new feature alarms on day one. New elements → "needs-baseline" queue.
- **Severity = stakes(surface, element) × confidence(#truths agreeing, peer-divergence magnitude) × blast-radius(sessions/% affected).**
- **Dedup to issues, not events:** cluster by `(surface, page, element, primitive)` → one flag with N affected sessions + replay exemplars, not N flags.

## Output shape

A flag is an **issue**, not a raw event — and it's actionable in one 20-second replay watch:

```
surface:        debtor | client
route:          /pay/{token}        # templated, no PII
element:        stable selector / autocapture role+text
primitives:     [effortful_no_op, interaction_then_abandon]
verdict:        no_effect=true · goal_reached=false ·
                peer_effect_rate=0.94 vs this=0.00 · funnel: review→pay stalled
severity:       SEV1   (+ the formula inputs)
reason:         "Pay-now button on /pay produced no state change for 41/130
                 sessions in 24h; 0% proceeded vs 94% peer baseline."
evidence:       affected_sessions=41 (32%) · 3 timestamped replay deep-links
                · first_seen · trend(new|ongoing) · release tag if joinable
confidence:     high | med  (+ why)
```

Routing by severity: **SEV1 debtor → page on-call now; SEV3–4 → daily digest.** State an explicit precision target (e.g. ≥80% of SEV1/2 flags real on review) and tune thresholds against it.

## Privacy / compliance

Debtor payment/dispute replays are **real PII** — names, debt amounts, card fields, dispute free-text, possibly hardship/health reasons. Posture:

- **Mask at capture, not after.** Default-mask all inputs; aggressively mask text on debtor surfaces; **block payment-card DOM from recording entirely** (cards belong in a PSP iframe and should never be in rrweb). Allowlist only the *structural* facts the primitives need — element role, **state**, and *whether* an error showed — never its text.
- **Never ship raw replay to a third-party LLM.** Detection runs on the **event/metadata stream** (event types, selectors, states, timings, funnel position) — which is all the primitives need anyway — **not on rrweb pixels**. If an LLM is used at all, it's to summarize **aggregated, de-identified issue metadata**, never raw frames or PII. Strong default: detection stays in-house on structured events.
- **Retention & access.** Short TTL on debtor replays (e.g. 30 days), shorter on PII-tagged; auto-purge; replay links are **permissioned, not public URLs**; access logged. Region/data-residency per client contract — debt collection is regulated (FDCPA / GDPR). **Right-to-erasure** must purge a debtor's replays *and* any flag exemplars referencing them.
- The **flag itself carries no PII** (templated routes, element refs, counts) → safe to drop in Slack/email; only the gated replay link reveals more.

## What I DON'T know yet (unknowns · where I'd get ground truth · starting signals)

**Unknowns → where I'd resolve them:**
1. *What's actually captured today* — is autocapture on for both surfaces? Is element **state** (disabled/aria) in the properties? Are card fields masked / in an iframe? → PostHog project settings + a 7-day sample of events per surface.
2. *Goal events* — are there clean **server-confirmed** successes (`payment_succeeded`, `dispute_submitted`, `report_rendered`, `import_completed`)? Client-side success lies (optimistic UI). → Backend event catalog. Ground truth for "did it really succeed" must be **server-side**, joined to the session.
3. *Element stability* — are selectors stable across deploys or hashed/dynamic (breaks baselining)? → Inspect the frontend build; need stable `data-testid`/capture attrs on key controls.
4. *Volume* — enough traffic per element to baseline, especially on low-traffic debtor pages? → Traffic by route; low-volume elements need longer windows or pooling.
5. *Deploy markers* — can flags join to releases (catch regressions, suppress "expected change after deploy")? → CI/CD release events into PostHog.

**How I'd get ground truth / bootstrap:**
- **Recall set:** past user-reported bugs / incidents → find those sessions → confirm the primitives fire on them.
- **Precision set:** clean successful sessions → must *not* flag.
- **Shadow mode for 2–4 weeks** (flags to a private channel, no paging) → hand-label → measure precision/recall → tune the ≥2-truth thresholds and severity → *then* enable routing.

**Starting signals (the wedge — cheapest, highest yield):** `effortful_no_op` + `interaction_then_abandon-without-goal`, on the **debtor payment page only**, with **server-side `payment_succeeded`** as goal truth and a **7-day per-element peer baseline**. Highest stakes, clearest success event, where we'd otherwise *never hear about the bug*.

## Clarifying questions

Three that change the design — not fifteen to look thorough.

1. **Is there a reliable *server-side* success event per goal (payment/dispute/report/import) I can join to a PostHog session?**
   - *Why it matters:* session-goal truth (#2) and funnel/peer truths need a trustworthy success signal; client-side success lies under optimistic UI.
   - *Default if unanswered:* use the strongest client-side proxy (a `/success` or `/confirmation` `$pageview`), flag a confidence tier lower, note higher FP risk.
   - *What changes:* with server truth, precision jumps and SEV1 paging is safe; without it, everything drops a tier and I lean harder on peer-divergence.

2. **Is element STATE (disabled, aria-disabled, validation-error presence) in autocapture today, and do key controls have stable selectors?**
   - *Why it matters:* the "no-op on a *blocked* control" discriminator and element baselining both need stable identity + state.
   - *Default if unanswered:* detect no-op purely from "no effect after repeated action," ignore explicit disabled-state — works but misses the cleanest discriminator and is noisier.
   - *What changes:* with state + stable selectors I cleanly separate "disabled submit" (high-conf bug) from a dead-but-enabled control; without, I need more corroboration to hit the precision bar.

3. **What precision bar and routing do you want for v1 — page on-call on SEV1 immediately, or shadow-mode digest until we've measured — and what false-positive rate is tolerable?**
   - *Why it matters:* the whole design biases to precision; the tolerated FP rate sets the ≥2-truth thresholds and the volume floor, and decides page-vs-digest.
   - *Default if unanswered:* shadow mode 2–4 weeks (no paging), daily digest, hand-label, then enable SEV1 paging once measured precision ≥ ~80%.
   - *What changes:* immediate paging → raise thresholds (≥3 truths, higher volume floor) → fewer, higher-confidence flags, lower recall. Digest-only → loosen for coverage.

## Risks & edge cases

- **Optimistic UI / SPA:** client "success" shows before the server confirms; a state change can happen while the op still failed → why server truth matters.
- **Slow networks / mobile debtors:** latency mimics dead controls. Distinguish "no effect ever" from "effect arrived late"; segment by connection where possible.
- **Intended multi-click controls** (steppers, +/−, pagination, "load more"): effect-per-click + peer baseline save us — peers also click 5× and proceed. No hardcoded allowlist; it's learned.
- **Low-traffic elements:** can't baseline → watchlist + longer windows, never page.
- **A/B tests / feature flags:** a variant *legitimately* changes behavior → join flag context and baseline per-variant, or suppress on flagged variants.
- **Bots / automation** on the dashboard: weird patterns → exclude.
- **Deploy-induced baseline shifts** (redesign changes selectors/flows): expect a quiet period; use release markers so we don't flag *the change itself*.
- **Privacy leak via the flag:** dispute free-text must never enter the reason string or selector text → templatize routes, never echo input values.
- **Alert fatigue from one broken element across thousands of sessions:** dedup to a single issue + count, not thousands of flags.
- **Survivorship on debtor pages:** abandoners never return, so there's no "retry success" to learn from → weight first-session abandonment heavily here.
- **Replay sampling:** if replays are sampled, recall drops — detecting on *events* (fuller than replays) mitigates this.
