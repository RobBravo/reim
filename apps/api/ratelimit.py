"""Counting requests, and deciding who made them.

Pure by construction: ``now`` is injected and nothing here reads a clock, a
request object or a database. That is what lets the window boundary be asserted
at an exact instant rather than by sleeping, and the identity rules be asserted
against plain strings.

The identity half matters more than the arithmetic. Trusting
``X-Forwarded-For`` by default is the standard way to build a limiter that
enforces nothing: the header is attacker-controlled unless something you run
wrote it, so a client sets it to a fresh value per request and never shares a
bucket with itself.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Ceiling on distinct identities held in memory.
#:
#: Without it, a client rotating source addresses grows the limiter without
#: bound and turns the thing meant to shed load into a way to exhaust the
#: process. When the ceiling is reached, eviction happens in two stages:
#: first, entries from earlier windows are dropped (they were about to reset
#: anyway); second, if that is not enough, the oldest tracked entries from
#: the current window are removed regardless of their state. An evicted
#: identity starts counting again from zero on its next request. This is
#: acceptable because the identity is normally the socket peer, which a
#: caller cannot choose; forcing your own eviction requires generating
#: distinct source addresses, which already grants an unthrottled bucket per
#: address under any per-IP limiter.
MAX_TRACKED_IDENTITIES = 10_000

#: Fallback identity when the transport reports no peer.
UNKNOWN_PEER = "unknown"


@dataclass(frozen=True)
class Decision:
    """Whether a request may proceed, and when to come back if not."""

    allowed: bool
    retry_after_seconds: int


class FixedWindowLimiter:
    """Counts requests per identity in fixed, wall-clock-aligned windows.

    State lives on the instance, so the application owns one and tests own
    their own. A module-level counter would leak a limit between tests and
    between applications built in one process.
    """

    def __init__(self, *, window_seconds: int) -> None:
        self._window = window_seconds
        self._counts: dict[str, tuple[float, int]] = {}

    @property
    def tracked(self) -> int:
        """How many identities are currently held. Bounded by the ceiling."""
        return len(self._counts)

    def check(self, identity: str, limit: int, *, now: float) -> Decision:
        """Record one request and say whether it is within ``limit``."""
        window_start = now - (now % self._window)
        recorded_start, count = self._counts.get(identity, (window_start, 0))
        if recorded_start != window_start:
            count = 0

        count += 1
        self._counts[identity] = (window_start, count)
        if len(self._counts) > MAX_TRACKED_IDENTITIES:
            self._prune(window_start)

        if count <= limit:
            return Decision(allowed=True, retry_after_seconds=0)

        # Ceil, and never zero: a client honouring a 0 would retry into the
        # same refusal.
        remaining = window_start + self._window - now
        return Decision(allowed=False, retry_after_seconds=max(1, int(remaining) + 1))

    def _prune(self, window_start: float) -> None:
        """Enforce the tracked identity ceiling in two stages.

        First, drop identities from earlier windows (they were about to reset).
        Second, if the current window alone exceeds the ceiling, keep only the
        most recently **inserted** identities. This FIFO eviction (not LRU) is
        deliberately asymmetric: once the cap is reached within a window, older
        tracked identities are evicted before newer ones, even if the newer
        ones sent more requests. This is the simplest bounding strategy and is
        safe because evicted identities start fresh; the attacker gains nothing
        that distinct source addresses did not already give.
        """
        self._counts = {
            identity: entry for identity, entry in self._counts.items() if entry[0] == window_start
        }
        # If still over limit, keep only the most recent MAX_TRACKED_IDENTITIES
        if len(self._counts) > MAX_TRACKED_IDENTITIES:
            items = list(self._counts.items())
            self._counts = dict(items[-MAX_TRACKED_IDENTITIES:])


def client_identity(peer: str | None, forwarded_for: str | None, *, trusted_proxy_hops: int) -> str:
    """Return the address a request should be counted against.

    ``trusted_proxy_hops`` is how many proxies **you run** sit in front of this
    process. At 0 the socket peer is used and ``X-Forwarded-For`` is ignored
    entirely, because a client can set it to anything.

    At *n*, the identity is the *n*-th entry from the right — the one the
    outermost proxy you controlled appended. Setting it higher than the number of
    proxies you actually run hands the choice back to the client, which is the
    bypass this exists to prevent; so a header with fewer entries than claimed
    falls back to the peer rather than trusting whatever arrived.
    """
    fallback = peer or UNKNOWN_PEER
    if trusted_proxy_hops <= 0 or not forwarded_for:
        return fallback

    entries = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
    if len(entries) < trusted_proxy_hops:
        return fallback
    return entries[-trusted_proxy_hops]
