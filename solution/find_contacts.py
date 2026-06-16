"""Contact Finder — minimal slice (Stage B).

Reads the company CSV, queries the (mocked) providers, cross-references them,
scores a confidence, and returns ONE decision-maker contact per company — or an
honest needs_human_review when it can't verify one.

Adapts to challenge/CLARIFICATIONS.md:
  - Persona priority: AP / accounts-payable FIRST, then owner/founder, then CFO,
    then office manager. (My PLAN.md had owner first; the clarifications flip it.)
  - Confidence threshold = 70: below it, the contact value is withheld and the
    row is flagged for a human.
  - Precision over recall: a confident, traceable contact beats three guesses, so
    a high review rate on genuinely hard rows is the desired outcome, not a miss.
  - Provenance: every emitted value carries the source_url(s) it came from, and a
    contact is never returned unless it traces to at least one source.

Run:  python find_contacts.py        # uses the challenge CSV + mocks by default
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from providers import MockProvider, ProviderResult

THRESHOLD = 70  # from CLARIFICATIONS.md

# Persona priority (lower = more wanted). Reordered to match the clarifications.
PERSONA_PRIORITY = {
    "accounts payable": 0, "accounts-payable": 0, "ap": 0,
    "owner": 1, "founder": 1, "president": 1,
    "cfo": 2, "finance": 2,
    "office manager": 3, "manager": 3,
}
NON_DECISION_MAKER = {"registered agent"}  # a legal proxy, not someone we can collect from
GENERIC_LOCALPARTS = {"info", "office", "sales", "contact", "admin",
                      "hello", "support", "billing"}

# --- scoring weights (explainable on purpose) ---
W_PERSON = 40          # we identified an actual person
W_CORROBORATED = 22    # a second independent source backs it
W_MULTI = 16           # 2+ independent agreements
W_ATTRIBUTABLE = 6     # the contact value ties to that person
W_DECISION_ROLE = 5    # role is a real decision-maker
P_GENERIC = 18         # contact is a role-less inbox
P_NON_DM = 30          # role is explicitly not a decision-maker
S_CONFLICT = 25        # sources name different people -> not safe to act on
S_PHONE_ONLY = 60      # corroborated phone but nobody named


def _norm_name(name: str | None) -> str:
    if not name:
        return ""
    n = name.lower()
    n = re.sub(r"\b(dr|mr|mrs|ms|jr|sr)\.?\b", "", n)  # drop honorifics
    n = re.sub(r"\(.*?\)", "", n)                       # drop "(manager)" etc.
    n = re.sub(r"[^a-z ]", "", n)
    return " ".join(n.split())


def _names_match(a: str | None, b: str | None) -> bool:
    """Loose match so 'Bob'/'Robert' and 'S. Murphy'/'Sean Murphy' still line up."""
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na.split()[-1] == nb.split()[-1]:   # same surname
        return True
    return bool(set(na.split()) & set(nb.split()))


def _email_matches_person(email: str | None, name: str | None) -> bool:
    if not email or not name:
        return False
    local = email.split("@", 1)[0].lower()
    if local in GENERIC_LOCALPARTS:
        return False
    tokens = [t for t in _norm_name(name).split() if t]
    return any(t in local or local in t for t in tokens)


def _is_generic_email(value: str | None) -> bool:
    return bool(value) and "@" in value and value.split("@", 1)[0].lower() in GENERIC_LOCALPARTS


def _role_tier(role: str | None):
    if not role:
        return None
    r = role.lower().strip()
    if r in NON_DECISION_MAKER:
        return "disqualified"
    for key, tier in PERSONA_PRIORITY.items():
        if key in r:
            return tier
    return None


def resolve(company: str, results: list[ProviderResult]) -> dict:
    by = {r.provider: r for r in results}
    registry, listing, enrichment = by.get("registry"), by.get("listing"), by.get("enrichment")
    reasons: list[str] = []
    provenance = [r.source_url for r in results if r.source_url]

    if not results:
        return _row(company, "", "", "", 0, "none", True,
                    [], ["no source returned anything for this company"])

    person = (registry.name if registry and registry.name
              else listing.name if listing and listing.name else None)
    role = registry.role if registry and registry.role else None

    # --- corroboration: independent sources lining up on the same person/contact ---
    agreements = 0
    if registry and listing and _names_match(registry.name, listing.name):
        agreements += 1
        reasons.append("registry and listing name agree")
    if enrichment and person and _email_matches_person(enrichment.email, person):
        agreements += 1
        reasons.append("enrichment email matches the person")
    phone_corroborated = bool(listing and enrichment and listing.phone
                              and listing.phone == enrichment.phone)
    if phone_corroborated:
        reasons.append("phone confirmed by two independent sources")

    conflict = bool(registry and listing and registry.name and listing.name
                    and not _names_match(registry.name, listing.name))

    # --- pick a contact value: attributable email first, then a phone ---
    contact = ""
    if enrichment and enrichment.email and not _is_generic_email(enrichment.email) \
            and (person is None or agreements or _email_matches_person(enrichment.email, person)):
        contact = enrichment.email
    else:
        for src in (listing, enrichment, registry):
            if src and getattr(src, "phone", None):
                contact = src.phone
                break
        if not contact and enrichment and enrichment.email:  # only a generic inbox left
            contact = enrichment.email

    # --- score (0-100), every move logged ---
    if conflict:
        score = S_CONFLICT
        reasons.append("sources disagree on who the contact is -> not safe to act on")
    elif person:
        score = W_PERSON
        reasons.append("named person identified")
        if agreements >= 1 or phone_corroborated:
            score += W_CORROBORATED
            reasons.append("corroborated by an independent source")
        if agreements >= 2 or (agreements >= 1 and phone_corroborated):
            score += W_MULTI
            reasons.append("multiple independent sources agree")
        if contact and not _is_generic_email(contact):
            score += W_ATTRIBUTABLE
            reasons.append("contact is directly attributable to the person")
    elif phone_corroborated:
        score = S_PHONE_ONLY
        reasons.append("phone corroborated but no person identified")
    else:
        score = 40
        reasons.append("single unverifiable source")

    tier = _role_tier(role)
    if tier == "disqualified":
        score -= P_NON_DM
        reasons.append(f"role '{role}' is not a decision-maker")
    elif tier is not None:
        score += W_DECISION_ROLE
        reasons.append(f"role '{role}' is a valid decision-maker")

    if _is_generic_email(contact):
        score -= P_GENERIC
        reasons.append("contact is a generic inbox, not a person")

    score = max(0, min(100, score))

    needs_review = score < THRESHOLD or not contact
    if needs_review and contact:
        reasons.append(f"below threshold {THRESHOLD} -> contact withheld, sent to human review")

    return _row(
        company,
        person or "",
        role or "",
        "" if needs_review else contact,
        score,
        "+".join(r.provider for r in results),
        needs_review,
        provenance,
        reasons,
    )


def _row(company, name, role, contact, score, source, review, provenance, reasons) -> dict:
    return {
        "company_name": company,
        "contact_name": name,
        "contact_role": role,
        "contact_email_or_phone": contact,
        "confidence_score": score,
        "source": source,
        "needs_human_review": review,
        "provenance": provenance,
        "reasons": reasons,
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Contact Finder — minimal slice")
    ap.add_argument("--csv", default=root / "challenge" / "data" / "companies.csv")
    ap.add_argument("--mocks", default=root / "challenge" / "mocks" / "enrichment_responses.json")
    args = ap.parse_args()

    provider = MockProvider(Path(args.mocks))
    rows = []
    with open(args.csv, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(resolve(r["company_name"], provider.lookup(r["company_name"])))

    # --- write outputs ---
    out_dir = Path(__file__).resolve().parent
    cols = ["company_name", "contact_name", "contact_role",
            "contact_email_or_phone", "confidence_score", "source", "needs_human_review"]
    with open(out_dir / "output.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in rows:
            w.writerow({k: row[k] for k in cols})
    (out_dir / "output.json").write_text(json.dumps(rows, indent=2))

    # --- human-readable summary ---
    confident = [r for r in rows if not r["needs_human_review"]]
    print(f"{len(rows)} companies | {len(confident)} confident contacts | "
          f"{len(rows) - len(confident)} need human review (precision over recall)\n")
    print(f"{'COMPANY':<30} {'SCORE':>5}  {'REVIEW':<6} CONTACT")
    print("-" * 78)
    for r in rows:
        flag = "YES" if r["needs_human_review"] else "no"
        print(f"{r['company_name']:<30} {r['confidence_score']:>5}  {flag:<6} "
              f"{r['contact_email_or_phone'] or '—'}")


if __name__ == "__main__":
    main()
