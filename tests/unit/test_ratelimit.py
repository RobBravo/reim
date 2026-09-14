"""The limiter's arithmetic and its notion of who is calling.

Pure: no clock, no request object, no database. ``now`` is injected, so the
window boundary is asserted directly instead of by sleeping, and the identity
rules are asserted against strings rather than through a served request.

The identity tests carry the most weight here. A limiter that can be bypassed
by setting a header is not a limiter, and that is a one-line mistake to make.
"""

from __future__ import annotations

from apps.api.ratelimit import (
    MAX_TRACKED_IDENTITIES,
    FixedWindowLimiter,
    client_identity,
)

PEER = "203.0.113.9"


def test_requests_under_the_limit_are_allowed() -> None:
    limiter = FixedWindowLimiter(window_seconds=60)

    for _ in range(3):
        assert limiter.check("a", 3, now=1000.0).allowed


def test_the_request_that_exceeds_the_limit_is_refused() -> None:
    limiter = FixedWindowLimiter(window_seconds=60)
    for _ in range(3):
        limiter.check("a", 3, now=1000.0)

    assert limiter.check("a", 3, now=1000.0).allowed is False


def test_a_new_window_starts_the_count_again() -> None:
    limiter = FixedWindowLimiter(window_seconds=60)
    for _ in range(3):
        limiter.check("a", 3, now=1000.0)

    assert limiter.check("a", 3, now=1060.0).allowed


def test_the_first_instant_of_a_window_is_allowed() -> None:
    """The boundary itself, which is where an off-by-one would hide.

    1020.0 is exactly a window start for a 60-second window; a request there
    belongs to the new window, not the old one.
    """
    limiter = FixedWindowLimiter(window_seconds=60)
    for _ in range(3):
        limiter.check("a", 3, now=1019.9)

    assert limiter.check("a", 3, now=1020.0).allowed


def test_identities_are_counted_separately() -> None:
    limiter = FixedWindowLimiter(window_seconds=60)
    for _ in range(3):
        limiter.check("a", 3, now=1000.0)

    assert limiter.check("b", 3, now=1000.0).allowed


def test_retry_after_counts_seconds_to_the_window_reset() -> None:
    """A client that honours it must not come back while still refused.

    A 60-second window containing 1000.0 runs [960, 1020), so at 1010.0 there
    are 10 seconds left and the answer is 11 — rounded up, never down, or a
    client returns into the same refusal.
    """
    limiter = FixedWindowLimiter(window_seconds=60)
    limiter.check("a", 1, now=1000.0)

    decision = limiter.check("a", 1, now=1010.0)

    assert decision.allowed is False
    assert decision.retry_after_seconds == 11


def test_retry_after_is_never_zero() -> None:
    """Zero would invite an immediate retry that is still refused.

    1019.9 is the last tenth of a second of the window that began at 960, so
    the true remainder is 0.1 — the case where truncating instead of rounding
    up would answer zero.
    """
    limiter = FixedWindowLimiter(window_seconds=60)
    limiter.check("a", 1, now=1000.0)

    decision = limiter.check("a", 1, now=1019.9)

    assert decision.allowed is False
    assert decision.retry_after_seconds == 1


def test_tracked_identities_are_bounded() -> None:
    """A client rotating addresses must not grow the limiter without bound.

    Memory held by the limiter is otherwise attacker-controlled, which turns
    the thing meant to shed load into a way to exhaust the process.
    """
    limiter = FixedWindowLimiter(window_seconds=60)

    for index in range(MAX_TRACKED_IDENTITIES + 500):
        limiter.check(f"ip-{index}", 10, now=1000.0)

    assert limiter.tracked <= MAX_TRACKED_IDENTITIES


def test_without_trusted_proxies_a_forged_header_is_ignored() -> None:
    """The assertion this module exists for.

    A client that can choose its own identity gets a fresh allowance on every
    request, and the limiter enforces nothing while reporting healthy.
    """
    identity = client_identity(PEER, "1.2.3.4, 5.6.7.8", trusted_proxy_hops=0)

    assert identity == PEER


def test_one_trusted_hop_takes_the_entry_its_proxy_wrote() -> None:
    """Behind one reverse proxy, the rightmost entry is the real client."""
    identity = client_identity("10.0.0.1", "198.51.100.7", trusted_proxy_hops=1)

    assert identity == "198.51.100.7"


def test_two_trusted_hops_step_back_two_entries() -> None:
    identity = client_identity("10.0.0.1", "198.51.100.7, 10.0.0.2", trusted_proxy_hops=2)

    assert identity == "198.51.100.7"


def test_a_header_shorter_than_the_trusted_hops_falls_back_to_the_peer() -> None:
    """Fewer entries than claimed means the chain is not what was configured.

    Taking the leftmost entry there would take whatever the client sent, which
    is the bypass this setting exists to prevent.
    """
    identity = client_identity(PEER, "1.2.3.4", trusted_proxy_hops=3)

    assert identity == PEER


def test_whitespace_around_forwarded_entries_is_ignored() -> None:
    identity = client_identity("10.0.0.1", "  198.51.100.7 ,  10.0.0.2  ", trusted_proxy_hops=2)

    assert identity == "198.51.100.7"


def test_a_missing_peer_still_yields_an_identity() -> None:
    """``request.client`` is ``None`` for some transports; it must not crash."""
    assert client_identity(None, None, trusted_proxy_hops=0)


def test_an_empty_forwarded_header_falls_back_to_the_peer() -> None:
    assert client_identity(PEER, "", trusted_proxy_hops=1) == PEER


def test_an_evicted_identity_starts_counting_again() -> None:
    """Evicted identities get a fresh allowance, not a penalty.

    When the limiter exceeds its identity ceiling, the oldest entries in the
    current window are removed to enforce the bound. This grants no lasting
    advantage: forcing your own eviction requires source addresses, which
    already buy you an unthrottled bucket each under any per-IP limiter.
    """
    limiter = FixedWindowLimiter(window_seconds=60)

    # Exhaust identity "early"'s allowance
    for _ in range(3):
        limiter.check("early", 3, now=1000.0)
    assert limiter.check("early", 3, now=1000.0).allowed is False

    # Fill the limiter past its ceiling so "early" is evicted (FIFO)
    for index in range(MAX_TRACKED_IDENTITIES):
        limiter.check(f"fill-{index}", 10, now=1000.0)

    # "early" has been evicted. Its next request should be allowed.
    assert limiter.check("early", 3, now=1000.0).allowed
