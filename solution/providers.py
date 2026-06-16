"""Data providers behind one interface.

In production these are three independent services: a business-registry lookup,
a web/maps listing, and an email/phone enrichment API. For this challenge they
read canned fixtures so the slice runs offline (no real scraping). The point is
the *interface*: swap MockProvider for a real client and the pipeline upstream
doesn't change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ProviderResult:
    """One source's answer for one company. Any field can be missing."""
    provider: str                       # "registry" | "listing" | "enrichment"
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    provider_confidence: Optional[int] = None   # enrichment's self-reported score, NOT ours
    source_url: Optional[str] = None            # provenance — carried through to output


class MockProvider:
    """Serves the three canned sources per company. A missing key or a null
    field means 'this source found nothing' — a real, expected outcome."""

    SOURCES = ("registry", "listing", "enrichment")

    def __init__(self, fixtures_path: Path):
        self._data = json.loads(Path(fixtures_path).read_text())

    def lookup(self, company_name: str) -> list[ProviderResult]:
        entry = self._data.get(company_name, {})
        results: list[ProviderResult] = []
        for src in self.SOURCES:
            raw = entry.get(src)
            if not raw:
                continue  # absent/None source = a "not found" from that provider
            results.append(
                ProviderResult(
                    provider=src,
                    name=raw.get("name"),
                    role=raw.get("role"),
                    email=raw.get("email"),
                    phone=raw.get("phone"),
                    provider_confidence=raw.get("provider_confidence"),
                    source_url=raw.get("source_url"),
                )
            )
        return results
