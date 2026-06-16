# ABOUT.md

## Why this role
AI-native engineering is just how I already work — I run a production stack of LLM agents and live in Claude Code daily, so most of your "this is different" section reads as normal to me. The collections problem is the kind I like: the hard part isn't "can an LLM do it," it's "can you trust it to," which is exactly the line I spend my time on. And "no layers between you and decisions, founder reviews every PR" is the environment I do my best work in.

## How I work with AI tools
Claude Code is my main loop — planning, building, refactoring across whole codebases — plus quick edits in Cursor. The judgment is in *where I trust it*: I trust the model for fluency and breadth (drafts, boilerplate, finding my way around unfamiliar code) and never for invariants. Anywhere correctness actually matters — a money path, a destructive query, a "this contact is verified" claim — I verify against the source or wrap it in a deterministic check instead of trusting the output.

Concretely on this challenge: I had the model draft the scoring, then I calibrated the weights by hand against the real fixtures and traced the edge cases myself (the conflict row, the registered-agent row, the no-name row), because that's exactly where a model hands you something plausible and wrong. The plan-first gate kept it on a short leash — the plan was the spec, and the build adapted to the clarifications, not to whatever the model felt like generating.

## My last project (structured)
A multi-tenant platform of LLM sales agents (WhatsApp + voice) I built and run solo for a non-technical company.

- **One ambiguity:** the spec never defined how the agent knows *which* item a user means when they just reply "yes" to one search result — no explicit "pick" signal, so it kept losing context and turning evasive. I resolved it with an auto-pick: a single match plus nothing specific said = treat it as the implicit selection and hydrate the full record.
- **One tradeoff:** deterministic guardrails over trusting the prompt. Anywhere the agent could misbehave (invent a booking, flip a buyer into a seller, promise data it didn't have), I added forced tool calls or a post-generation layer that rewrites/blocks unsupported claims — more code and slightly less flexibility, for reliability I can guarantee.
- **One mistake:** a user-facing dodge kept appearing — the exact evasion I'd prompted against. I spent an hour "fixing the prompt," sure the model was lying. It wasn't: it honestly had no data because the context-builder never loaded the record. I'd misdiagnosed a data-layer bug as a model bug. Now when an LLM answers badly, I check what it can *see* before I blame how it *thinks*.
- **One review comment that changed my mind:** I claimed a feature flag was still on the old version "because the code default says so." The reviewer: *"you have access — check the live row, don't infer it."* The DB said the opposite. I verify runtime state now instead of reasoning from code and docstrings.

## What I'd improve about this challenge / your CLAUDE.md
- **The mocks don't exercise the top persona.** Your clarifications make AP / accounts-payable the #1 target, but no mock row exposes an AP role — so a candidate can *claim* AP-first prioritization without the data ever testing it. One AP row (ideally conflicting with an owner) would separate people who actually reordered from people who just said they did.
- **A small tension in CLAUDE.md:** "never use negative words (failed, unable, rejected)" is right for customer-facing copy, but this challenge rewards being blunt about uncertainty — "cannot verify," "needs human review." I'd scope that rule to user-facing text only; internal status and telemetry should stay honest, not euphemized. (Also worth noting: the CLAUDE.md is still the legacy Laravel one, so it doesn't quite map to the language-agnostic challenge.)
