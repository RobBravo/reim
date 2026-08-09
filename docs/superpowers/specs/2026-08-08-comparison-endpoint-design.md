# Cross-country comparison endpoint — design

Status: **approved, not yet implemented**
Date: 2026-08-08
Roadmap item: v0.3.0, piece B

---

## 1. What this adds, and why now

The roadmap asks for "cross-country comparison endpoints: one indicator, many
countries, aligned periods, with the unit and vintage differences made explicit
rather than smoothed over".

Until the previous increment there was nothing to compare — REIM held one
country. It now holds six, and measured against the database:

| Indicator | Countries | Observations | Distinct units |
|---|---|---|---|
| `exports_goods_monthly` | 6 | 2,616 | 1 |
| `imports_goods_monthly` | 6 | 2,616 | 1 |
| `trade_balance_goods_monthly` | 6 | 2,616 | 1 |

Ten further indicators exist for a single country each.

The existing `/api/v1/observations` already filters by **one** country. What a
client cannot do well for itself is align periods across countries and see, in
the payload, where a country simply has no figure. That alignment, and the
honesty about gaps, is what this endpoint is for.

## 2. The endpoint

```
GET /api/v1/compare
    ?indicator=exports_goods_monthly
    &country=NI&country=GT&country=CR
    &date_from=2020-01-01
    &date_to=2026-04-30
    &limit=500&offset=0
    &order=asc
```

| Parameter | Rules |
|---|---|
| `indicator` | Required. A REIM indicator code. Unknown code → `404`. |
| `country` | Repeatable, **2 to 20** values, ISO alpha-2 or alpha-3. Fewer than 2 → `422`; unknown code → `404`. |
| `date_from` / `date_to` | Optional bounds on `period_start`, inclusive. |
| `limit` / `offset` | The existing pagination dependency; `limit` is capped by `REIM_MAX_PAGE_SIZE`. |
| `order` | `asc` or `desc` on `period_start`. Default `asc`. |

**At least two countries are required.** This is a comparison endpoint; a
single-country request is nearly always a client bug, and the existing
`/observations` endpoint already serves that case better.

## 3. The response

```json
{
  "meta": { "total": 436, "limit": 500, "offset": 0, "returned": 436, "has_more": false },
  "indicator": {
    "code": "exports_goods_monthly",
    "name": "Merchandise exports FOB (monthly)",
    "frequency": "monthly"
  },
  "comparable": true,
  "comparability_notes": [],
  "series": [
    {
      "country_iso2": "NI",
      "country_iso3": "NIC",
      "country_name": "Nicaragua",
      "unit": "current USD",
      "currency_code": "USD",
      "source_keys": ["imf_imts_nicaragua"],
      "observations": 436,
      "first_period": "1990-01",
      "last_period": "2026-04"
    }
  ],
  "data": [
    {
      "period_start": "2026-04-01",
      "period_end": "2026-04-30",
      "period_label": "2026-04",
      "values": { "NIC": "601982690", "GTM": "1524586084", "CRI": null }
    }
  ]
}
```

### 3.1 The matrix is rectangular, and gaps are explicit

**Every row carries one entry per requested country, `null` where that country
has no figure for that period.** A gap is declared in the payload rather than
inferred by comparing lengths. This is what "aligned" means here, and it
follows REIM's rule that gaps are reported as gaps and never imputed.

Rows are the **union** of the periods the requested countries hold, filtered by
`date_from` / `date_to`. `meta` is the existing `PageMeta`, and `total` counts
periods, not observations.

Values are serialised as **strings**, matching how `ObservationRead` already
exposes `value_numeric`, so no precision is lost to JSON floats.

### 3.2 Comparability is declared, never decided

`comparable` is `false` when the requested countries' series differ in **unit
or currency** for this indicator. Differing **sources** are recorded in
`comparability_notes` but do **not** make `comparable` false: two publishers
measuring the same thing in the same unit is normal, not an incomparability.

`comparability_notes` is a list of human-readable strings, each naming what
differs and between which countries, for example:

* `"Costa Rica has no observations for this indicator."`
* `"Units differ: current USD (NIC, GTM), quetzales (GTM)."`
* `"Sources differ: imf_imts_nicaragua (NIC), banguat_trade (GTM)."`

A country with **no data at all** still appears in `series`, with
`observations: 0`, `first_period` and `last_period` `null`, and a note. Its
column is `null` throughout. Omitting it would hide the very fact worth
knowing.

`source_keys` is a **list**, because one country's series for an indicator may
legitimately come from more than one source over time.

## 4. Decisions

| # | Decision | Rationale |
|---|---|---|
| C1 | A dedicated endpoint rather than a repeatable `country` filter on `/observations`. | A flat list leaves alignment and gap handling to the client, which is the part that is easy to get wrong and is exactly what the roadmap asks REIM to solve. |
| C2 | Rectangular matrix with explicit `null`s. | "Gaps are reported as gaps." An absent key would force the client to cross-reference `series[].observations` to notice a hole. |
| C3 | `comparable` keyed on unit and currency only; source differences are notes. | Different publishers of the same unit is normal. Conflating it with a unit mismatch would cry wolf. |
| C4 | Minimum two countries, maximum twenty. | The minimum states the endpoint's purpose and catches a client bug; the maximum bounds the payload. REIM registers seven countries. |
| C5 | **No currency conversion, ever.** | It would require exchange rates and would publish figures no official source published — listed under "explicitly not planned". Heterogeneous units are surfaced, not reconciled. |
| C6 | Values serialised as strings. | Matches `ObservationRead`; JSON numbers would lose the precision `NUMERIC` preserves. |
| C7 | Only `ACTIVE` observations are compared. | Matches the default of `/observations`; superseded rows are not part of the current picture. |

## 5. Components

### 5.1 `reim/repositories/comparison.py` (new)

`reim/repositories/observations.py` is already 200 lines across ten functions,
and this query has a different shape, so it gets its own module.

```python
@dataclass(frozen=True, slots=True)
class ComparisonQuery:
    """Everything the comparison query needs, already resolved."""

    indicator_code: str
    country_ids: list[uuid.UUID]
    period_start_from: date | None = None
    period_start_to: date | None = None


def count_comparison_periods(session: Session, query: ComparisonQuery) -> int: ...


def fetch_comparison_rows(
    session: Session,
    query: ComparisonQuery,
    *,
    limit: int,
    offset: int,
    descending: bool = False,
) -> list[ComparisonCell]: ...


def summarise_series(session: Session, query: ComparisonQuery) -> list[SeriesSummary]: ...
```

`ComparisonCell` carries `period_start`, `period_end`, `period_label`,
`country_iso3` and `value_numeric`; the router pivots them into rows.
`SeriesSummary` carries the per-country unit, currency, source keys, count and
coverage span, computed by one grouped query rather than by scanning the cells,
so a country with zero observations still gets an entry.

### 5.2 `reim/schemas/comparison.py` (new)

`ComparisonIndicator`, `ComparisonSeries`, `ComparisonRow` and
`ComparisonResponse`, the last reusing `PageMeta` from `reim/schemas/common.py`
so pagination reads identically to every other endpoint.

`Page[T]` itself is **not** reused: it carries only `meta` and `data`, and this
response also needs `indicator`, `comparable`, `comparability_notes` and
`series`.

### 5.3 `apps/api/routers/comparison.py` (new)

`APIRouter(prefix="/api/v1/compare", tags=["comparison"])`, registered in
`apps/api/main.py` after the observations router.

It resolves the indicator and each country to database rows — raising
`ResourceNotFoundError` for an unknown code, which the existing error handler
renders as the standard `404` envelope — then calls the repository, pivots the
cells into rectangular rows, derives `comparable` and the notes from the series
summaries, and assembles the response.

## 6. Testing

Integration tests under `tests/integration/test_api.py`, against the seeded
PostgreSQL database, following the file's existing style:

* comparing `exports_goods_monthly` across all six countries returns 436 rows,
  each with six entries, none of them missing
* the values match `/observations` for the same country, indicator and period —
  the comparison must not transform anything
* `comparable` is `true` and `comparability_notes` empty for that request
* `date_from` / `date_to` narrow the rows, and `order=desc` reverses them
* pagination: `limit=10` returns 10 rows with `total` still 436 and
  `has_more` true
* one country, two countries, twenty-one countries → `422`, `200`, `422`
* an unknown indicator and an unknown country each → `404`
* comparing an indicator only Nicaragua holds — `ni_cpi_index_monthly` — puts
  the other countries in `series` with `observations: 0`, fills their columns
  with `null`, and adds a note naming them

Unit tests for the note-building and `comparable` logic live in
`tests/unit/test_comparison.py` and use **constructed** `SeriesSummary` values,
because the differing-unit case cannot be produced from real data today.

## 7. Risks

| Risk | Mitigation |
|---|---|
| The `comparable: false` branch cannot be exercised against real data — all three multi-country indicators are homogeneous. | Covered by unit tests over constructed summaries, and labelled as such rather than presented as verified against a live source. It becomes real when piece C lands national connectors. |
| Pivoting in Python could misalign a country's column. | The test comparing values against `/observations` for the same country and period is what catches it; a misalignment would show up as a wrong number, not a missing one. |
| A wide date range over many countries produces a large payload. | Rows are paginated by the existing dependency and capped by `REIM_MAX_PAGE_SIZE`; countries are capped at twenty. |

## 8. Out of scope

* Currency conversion, now or later — see C5.
* Derived comparisons: ratios, indices rebased to a common year, per-capita
  figures. REIM would be publishing numbers no source published.
* A CSV form of the comparison. `/observations/export.csv` already serves bulk
  extraction, and a pivoted CSV is a presentation concern.
* Comparing two different indicators against each other; this endpoint takes
  exactly one.
