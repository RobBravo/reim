"""``schedule.py``: turning a catalog into a crontab an operator can read.

Pure — a catalog and some strings in, text out — so all of it runs without a
database, a clock or a filesystem. The catalog-derived cases build their own
``SourceCatalog`` rather than reading the real one: the real catalog's frequency
mix is data that will change, and a test asserting "four blocks" would fail the
day someone adds a weekly source. One test below deliberately does read the real
catalog, for the one invariant worth pinning against real data.
"""

from __future__ import annotations

from pathlib import Path

from reim.core.constants import Frequency
from reim.domain.pipelines.schedule import (
    FREQUENCY_MINUTES,
    ScheduleEntry,
    build_schedule,
    render_crontab,
)
from reim.domain.pipelines.scheduling import DEFAULT_CRON_BY_FREQUENCY
from reim.domain.sources.catalog import SourceCatalog, SourceEntry, get_catalog

WORKING_DIR = Path("/opt/reim")


def _entry(key: str, frequency: Frequency, *, enabled: bool = True) -> SourceEntry:
    """A catalog entry that validates, varying only the key, cadence and state.

    Three of these values are load-bearing and cannot be swapped for
    plausible-looking alternatives: the host must not be a placeholder
    (``example.org`` and friends are rejected on an *enabled* source), a
    disabled source must carry a ``disabled_reason``, and ``connector`` is an
    all-lowercase **module** path — the field's pattern forbids a class name.
    """
    return SourceEntry(
        key=key,
        name=f"Source {key}",
        organization="BCN",
        category="exchange_rate",
        access_type="http_api",
        frequency=frequency,
        format="json",
        base_url="https://bcn.gob.ni/estadisticas",
        connector="reim.ingestion.connectors.nicaragua.bcn_exchange_rate",
        indicators=["ni_exchange_rate_official_daily"],
        enabled=enabled,
        disabled_reason=None if enabled else "licence forbids redistribution",
    )


def _catalog(*entries: SourceEntry) -> SourceCatalog:
    return SourceCatalog(version=1, sources=list(entries))


def _schedule(*entries: SourceEntry) -> list[ScheduleEntry]:
    return build_schedule(_catalog(*entries), working_dir=WORKING_DIR)


def test_only_cadences_present_in_the_catalog_get_a_block() -> None:
    """Seven frequencies exist; a crontab should carry only the ones in use.

    Blocks for cadences no source uses are noise the operator has to read and
    then delete.
    """
    entries = _schedule(_entry("a", Frequency.MONTHLY), _entry("b", Frequency.MONTHLY))

    ingestion = [entry for entry in entries if "run-all" in entry.command]
    assert len(ingestion) == 1
    assert "--frequency monthly" in ingestion[0].command


def test_each_cadence_gets_its_own_block() -> None:
    entries = _schedule(
        _entry("a", Frequency.DAILY),
        _entry("b", Frequency.MONTHLY),
        _entry("c", Frequency.ANNUAL),
    )

    cadences = [
        entry.command.split("--frequency ")[1] for entry in entries if "run-all" in entry.command
    ]
    assert sorted(cadences) == ["annual", "daily", "monthly"]


def test_the_emitter_rewrites_the_minute_and_nothing_else() -> None:
    """``DEFAULT_CRON_BY_FREQUENCY`` stays the authority on which days.

    A future edit that reformats more of the expression — the hour, or the day
    fields — fails here, which is the point: staggering is a minute-level
    concern and must not silently become a scheduling one.
    """
    for frequency in (Frequency.DAILY, Frequency.WEEKLY, Frequency.MONTHLY, Frequency.QUARTERLY):
        entries = _schedule(_entry("a", frequency))
        emitted = entries[0].expression.split()
        default = DEFAULT_CRON_BY_FREQUENCY[frequency].split()

        assert emitted[0] == str(FREQUENCY_MINUTES[frequency])
        assert emitted[1:] == default[1:]


def test_every_cadence_has_a_distinct_minute_inside_the_hour() -> None:
    """Two blocks sharing a minute would defeat the staggering entirely."""
    minutes = list(FREQUENCY_MINUTES.values())

    assert len(set(minutes)) == len(minutes)
    assert all(0 <= minute < 60 for minute in minutes)
    assert set(FREQUENCY_MINUTES) == set(Frequency)


def test_daily_keeps_the_top_of_the_hour() -> None:
    """It runs most often, so it is the one that should never move."""
    assert FREQUENCY_MINUTES[Frequency.DAILY] == 0


def test_each_block_names_the_pipelines_it_will_run() -> None:
    """``--frequency monthly`` is opaque; this output exists to be read first."""
    entries = _schedule(_entry("alpha", Frequency.MONTHLY), _entry("beta", Frequency.MONTHLY))

    block = next(entry for entry in entries if "run-all" in entry.command)
    assert "alpha" in block.comment
    assert "beta" in block.comment
    assert "2 pipeline(s)" in block.comment


def test_disabled_sources_are_absent_rather_than_commented_out() -> None:
    """The catalog records why a source is off; a commented line invites
    uncommenting it without reading that."""
    entries = _schedule(
        _entry("on", Frequency.MONTHLY), _entry("off", Frequency.WEEKLY, enabled=False)
    )
    text = render_crontab(entries)

    assert "off" not in text
    assert "weekly" not in text


def test_the_alert_check_is_emitted_last_and_after_the_ingestion_window() -> None:
    """Staleness is only meaningful once the day's ingestion has finished."""
    entries = _schedule(_entry("a", Frequency.DAILY))

    assert "alert check" in entries[-1].command
    ingestion_hour = int(entries[0].expression.split()[1])
    alert_hour = int(entries[-1].expression.split()[1])
    assert alert_hour > ingestion_hour


def test_an_empty_catalog_still_emits_the_alert_line() -> None:
    """A deployment with every source disabled still wants to hear about it."""
    entries = _schedule(_entry("off", Frequency.MONTHLY, enabled=False))

    assert len(entries) == 1
    assert "alert check" in entries[0].command


def test_the_rendered_text_is_shaped_like_a_crontab() -> None:
    """Five schedule fields then a command, on every non-comment line."""
    entries = _schedule(_entry("a", Frequency.DAILY), _entry("b", Frequency.MONTHLY))

    for line in render_crontab(entries).splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=5)
        assert len(fields) == 6
        assert all(field for field in fields[:5])


def test_the_working_directory_reaches_every_command() -> None:
    entries = _schedule(_entry("a", Frequency.DAILY))

    for entry in entries:
        assert str(WORKING_DIR) in entry.command


def test_every_frequency_the_real_catalog_uses_has_a_default_expression() -> None:
    """The one invariant worth pinning against real data.

    Everything else here builds its own catalog, because the real one's
    frequency mix will change. This assertion is the opposite: it must track
    reality, and it fails the day a source arrives with a cadence nothing knows
    how to schedule.
    """
    for entry in get_catalog().sources:
        assert entry.frequency in DEFAULT_CRON_BY_FREQUENCY
        assert entry.frequency in FREQUENCY_MINUTES
