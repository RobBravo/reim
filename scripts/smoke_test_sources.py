#!/usr/bin/env python
"""Manually verify that the official sources are still reachable and parseable.

**This script makes real network calls to official statistical agencies.** It is
deliberately not part of the test suite: CI must never depend on a third party's
uptime, and REIM should not poll public institutions on every push.

Run it when you suspect a source has changed, before enabling a new connector,
or on a slow schedule as an external monitor::

    python scripts/smoke_test_sources.py
    python scripts/smoke_test_sources.py --source worldbank_ni_cpi_inflation
    python scripts/smoke_test_sources.py --include-disabled

Nothing is written to the database: it only runs ``extract`` → ``transform`` →
``validate`` and prints what came back. Exit code is 1 if any source failed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reim.core.exceptions import REIMError
from reim.core.logging import configure_logging
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.registry import ConnectorRegistry


async def check(registry: ConnectorRegistry, key: str) -> bool:
    """Exercise one connector against the live source. Returns True on success."""
    registered = registry.get(key)
    connector = registered.build()
    label = f"{key:32}"

    if not registered.enabled:
        reason = (registered.entry.disabled_reason or "").strip().split("\n")[0]
        print(f"  ○ {label} DISABLED — {reason[:90]}")

    try:
        raw = await connector.extract()
        observations = connector.transform(raw)
        results = connector.validate(observations)
    except REIMError as exc:
        print(f"  ✗ {label} {exc.code}: {exc.message[:100]}")
        return False
    except Exception as exc:
        print(f"  ✗ {label} {type(exc).__name__}: {str(exc)[:100]}")
        return False

    failed = [result for result in results if result.failed]
    if not observations:
        print(f"  ✗ {label} returned no observations")
        return False

    newest = max(observations, key=lambda obs: obs.period.start)
    oldest = min(observations, key=lambda obs: obs.period.start)
    print(
        f"  ✓ {label} {len(observations):4} obs  "
        f"{oldest.period.label}..{newest.period.label}  "
        f"latest={newest.value_numeric} {newest.unit}"
    )
    for result in failed:
        print(f"      ! [{result.severity.value}] {result.check_name}: {result.message[:80]}")
    return True


async def main() -> int:
    """Run the smoke test and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Check only this catalog key.")
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Also check sources the catalog marks disabled.",
    )
    args = parser.parse_args()

    configure_logging()
    registry = ConnectorRegistry(load_catalog())

    keys = [args.source] if args.source else registry.keys(enabled_only=not args.include_disabled)

    print(f"Checking {len(keys)} source(s) against the live services.\n")
    results = [await check(registry, key) for key in keys]

    succeeded = sum(results)
    print(f"\n{succeeded}/{len(results)} source(s) reachable and parseable")
    return 0 if succeeded == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
