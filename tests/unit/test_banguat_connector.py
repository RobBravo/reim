"""Banguat daily exchange rate, replayed from the recorded response."""

from __future__ import annotations

import re
from datetime import date

_VAR = re.compile(r"<Var>.*?</Var>", re.S)


def test_the_fixture_holds_the_whole_published_history(banguat_rango_xml: str) -> None:
    """A regrab that silently narrows the window would break every count below."""
    assert len(_VAR.findall(banguat_rango_xml)) == 13365
    assert "<fecha>01/01/1990</fecha>" in banguat_rango_xml
    assert "<fecha>09/08/2026</fecha>" in banguat_rango_xml


def test_the_fixture_keeps_the_liberalisation_rows(banguat_rango_xml: str) -> None:
    """1990-11-08: the buy rate fixed at 5.15 while the sell rate floated below."""
    assert "<fecha>08/11/1990</fecha><venta>4.62181</venta><compra>5.15</compra>" in (
        banguat_rango_xml.replace("\r\n", "").replace("\n", "")
    )


def test_the_fixture_skips_the_days_the_source_skips(banguat_rango_xml: str) -> None:
    """Five days are absent in 36 years; they are the source's history, not a fault."""
    for missing in (
        date(2000, 4, 2),
        date(2000, 5, 1),
        date(2001, 9, 2),
        date(2004, 3, 6),
        date(2004, 3, 7),
    ):
        assert f"<fecha>{missing:%d/%m/%Y}</fecha>" not in banguat_rango_xml
