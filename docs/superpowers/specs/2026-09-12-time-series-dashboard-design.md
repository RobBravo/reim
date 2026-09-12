# The time-series dashboard — design

REIM's third web page, and the last of v0.4.0: one indicator plotted over time
across several countries, server-rendered as SVG, with no JavaScript at all.

This settles the charting decision the two previous increments deferred.
Everything measured below was checked against the repository on 2026-09-12.

## 1. What exists, and what this adds

The data work is done. `/api/v1/compare` is not a list endpoint — it already
produces an aligned cross-country time series with its caveats attached:

| Piece | What it gives |
|---|---|
| `ComparisonQuery` (`reim/repositories/comparison.py:27`) | indicator code, country ids, optional date bounds |
| `fetch_comparison_cells(session, query, *, limit, offset, descending=False)` (`:113`) | one `ComparisonCell` per country per period; **pagination slices periods, not rows** |
| `ComparisonCell` (`:37`) | `period_start`, `period_end`, `period_label`, `country_iso3`, `value_numeric`, `currency_code` |
| `summarise_series(session, query, countries)` (`:162`) | one `SeriesSummary` per requested country, **empty ones included** |
| `SeriesSummary` (`:52`) | `country_iso2/iso3/name`, `units`, `currency_codes`, `source_keys`, `organization_codes`, `observations`, `first_period`, `last_period` |
| `assess_comparability(summaries, definition)` (`reim/schemas/comparison.py:45`) | `(comparable, notes)` — turns on unit and currency |
| `levels_comparable(definition)` (`:23`) | False when the publisher defines the indicator differently per country |

So this increment adds **no repository query and no schema** — the first web
page that touches the backend not at all. It adds one route, one module of
pure geometry, two templates (`series.html` and `series_not_found.html`) and a
stylesheet section.

The registries it reads from: 63 indicators (`reim/domain/indicators/registry.py`)
and 7 countries (`reim/domain/countries/registry.py`).

## 2. The page, with no JavaScript

`GET /series`, driven by an ordinary `<form method="get">`: a `<select>` of
indicators, a `<select multiple>` of countries, and two optional date fields.
The browser serialises and reloads. Nothing else is needed, and nothing else is
added — decision D1 of the catalog design (server-rendered, no build step) is
not reopened for one page.

The view calls `fetch_comparison_cells`, `summarise_series` and
`assess_comparability` directly, never `/api/v1/compare` over HTTP (decision D3
of the catalog design, pinned by an existing guard test).

### 2.1 Currency conversion is out of scope, and the existing flag is why

`/compare` accepts `convert_to=USD`. This page does not offer it.

Differing currencies already make `comparable` false, which §4 routes to small
multiples — and that is the honest rendering of Nicaragua's GDP in córdobas
beside Guatemala's in quetzales. The flag does the work; drawing converted
figures would put published and derived values on one page and drag in the
whole `ConversionBlock` caveat apparatus (`converted`, `already_at_target`,
`no_rate`, `caveats`) to say which cells are which. That deserves its own
increment, not a checkbox on this one.

It also removes a problem the absence of JavaScript creates: the conversion
control is meaningful only for `currency_convertible` indicators, which is not
known until an indicator is chosen, so it would have to appear on the second
render and not the first.

## 3. The chart is a module of pure functions

`apps/web/charts.py`, new. `apps/web/routes.py` is already about 300 lines
carrying three pages; scales and axes belong beside neither the views nor the
templates.

```text
nice_ticks(minimum, maximum, count) -> list[float]
Scale(domain_min, domain_max, pixel_min, pixel_max).to_pixel(value) -> float
series_path(points, x_scale, y_scale) -> str
```

None of them touches a session, a request or a template. This is where the
real bugs live — axis ticks at 0.0000001 intervals, a zero-height domain when a
series is constant, a value outside the domain drawing off the canvas — and
therefore where the exhaustive tests go, with no database and no HTTP.

A constant series (`minimum == maximum`) is the case most likely to be written
wrongly: it must produce a usable domain rather than dividing by zero, and the
chart must still say what the constant value is.

## 4. When two lines may share an axis

**Overlay only when `comparable` and `levels_comparable` are both true.
Otherwise, small multiples — one panel per country, each with its own axis.**

The two flags are independent axes of the same question, and the page must
respect both:

* `comparable` is false when **units or currencies differ**. A shared axis
  between a percentage and millions of dollars is not misleading, it is
  meaningless.
* `levels_comparable` is false when **the publisher measures a different thing
  in each country**. Three indicators declare it — CEPAL's interest rates,
  whose own `calculation_methodology` field reads "According to the definition
  from each country". Panama's "lending rate" is the rate on one-year trade
  credit; Belize's "policy rate" is its central bank's lending rate. Units and
  currency agree, so `comparable` stays true and correct on the axes it
  measures, and a single chart would still tell the reader that one country
  sits "above" another when what differs is the instrument.

Small multiples lose exactly one thing: the comparison of heights. That was
the false one. Each country keeps its own shape and trend, which are the parts
that remain readable, and no shared axis exists to invite the wrong reading.
The comparability notes render above the panels either way.

### 4.1 A country whose own series changes unit is not drawn at all

`SeriesSummary.units` is a **tuple**, and its docstring says why: one country's
series can carry more than one unit over time. Its own axis cannot save it —
a line crossing the switch is wrong inside a single country, before any
comparison.

Such a country is **not charted**. Its values appear in the table with a
sentence naming the units it carries and saying the series is not drawn
because it changes unit mid-way. Drawing it and adding a footnote would ask
the reader to disbelieve the picture in front of them.

## 5. Volume, without altering anything

The application's own description states REIM "never converts currencies,
never rounds a published figure and never fills a gap". **Downsampling a chart
is exactly that** — discarding published points so the drawing comes cheaper.
So nothing is downsampled and no curve is smoothed.

Instead: **no default date window, and a cap of 1,500 periods per request.**

The cap bites only on daily series. 1,500 points is about four years of a daily
exchange rate, but 125 years of monthly data and 375 of quarterly — so annual,
quarterly and monthly indicators show their whole history, which is the point.
BCN's and Banguat's exchange rates are the only daily sources REIM reads.

When a range holds more, the page says so in terms the reader can act on —
*"this range holds 3,900 daily periods; the chart draws at most 1,500. Narrow
the dates."* — rather than truncating silently or smoothing the difference
away. A full rebuild is on the order of 61,700 observations across all
indicators, so no single series is large in absolute terms; density, not total
size, is what the cap addresses.

## 6. The nine states

Each gets its own sentence. The previous increment shipped a roadmap entry
claiming six states where the pages rendered seven, so this section counts
them and the count is part of the spec:

| # | Condition | What the page says |
|---|---|---|
| 1 | No selection yet (first visit) | The form, and what the page is for. Not an error and not an empty chart |
| 2 | Database unreachable | *The series cannot be read: the database is not responding.* |
| 3 | Indicator not registered | A new `series_not_found.html`, status 404, naming the indicator — built the way `run_not_found.html` is, not by reusing that template |
| 4 | Country code not registered | The same template and status, naming the country instead |
| 5 | Valid selection, no observations for any country | Names the indicator and the countries, and says none holds data |
| 6 | Some countries hold data, some do not | Charts those that do; names those that do not, rather than dropping them |
| 7 | `comparable` or `levels_comparable` false | Small multiples, with the comparability notes above them (§4) |
| 8 | One country's series changes unit | That country is not charted; its units are named and its values stay in the table (§4.1) |
| 9 | The range exceeds 1,500 periods | Says how many periods the range holds and asks for narrower dates (§5) |

States 2 and 3-4 are different failures and must not share wording: one is
REIM being unable to answer, the other is the reader having asked for something
that does not exist.

Database availability is discovered the way `load_pipeline_summaries` and
`load_runs_page` already discover it — by issuing the query and catching
`SQLAlchemyError`, never by a connectivity check beforehand.

## 7. Testing, and the D7 tension resolved by accessibility

Decision D7 of the catalog design says tests assert content, not markup. A
chart **is** markup. The resolution is not an exception to D7; it falls out of
making the page accessible.

**Beneath every chart sits the table of values.** It is at once the SVG's
accessible equivalent, the project's rule that every figure links back to its
source, and **what the tests assert**. The `<svg role="img">` carries a
`<title>` and `<desc>` naming the indicator, the countries and the period
range — also real content, also assertable.

So:

* `apps/web/charts.py` is unit-tested exhaustively, with no database: tick
  selection across magnitudes, the constant-series domain, values at and
  outside the domain bounds, an empty point list.
* The page's tests assert the table's figures, the series names, the source
  links, the comparability notes and the `<title>`/`<desc>` text.
* **No test asserts a `<path>`'s `d` attribute**, or any coordinate. A chart
  whose geometry changed by a pixel must not fail a test; a chart that lost a
  country must.
* Each of the nine states in §6 is tested on its own, asserting the absence of
  its neighbours' wording as well as the presence of its own.

The existing guard test that web views issue no outbound HTTP covers the new
route once it requests it — a claim the previous increment made falsely about
its own routes, so this time the route is added to that test explicitly.

## 8. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Server-rendered SVG, no JavaScript, no charting library | Keeps every earlier decision intact: no dependency, no build step, no CDN, and the page renders on a restricted network — the stated reason REIM is self-hostable. A vendored minified blob would sit oddly in a project whose premise is auditable provenance (§3) |
| **D2** | One indicator across N countries; not one country across N indicators | Mirrors `/compare`, whose comparability machinery exists for exactly this shape. The transverse view needs base-100 normalisation, and normalising is transforming (§1) |
| **D3** | Overlay only when `comparable` **and** `levels_comparable`; otherwise small multiples | The two flags are independent, and a shared axis is meaningless under the first and misleading under the second (§4) |
| **D4** | A country whose own series changes unit is not charted | Its own axis cannot rescue a line that crosses a unit switch (§4.1) |
| **D5** | No downsampling, ever; a stated 1,500-period cap instead | REIM alters nothing, and discarding published points to cheapen a drawing is altering. The cap bites only on the two daily sources (§5) |
| **D6** | No default date window | Annual, quarterly and monthly series show their whole history; only daily series meet the cap, which is the correct place for the friction (§5) |
| **D7** | The value table is the chart's accessible equivalent **and** the test surface | Resolves the markup/content tension by making the assertable thing the same thing a screen reader gets (§7) |
| **D8** | Currency conversion is out of scope | Differing currencies already route to small multiples, which is the honest rendering; converted figures need the whole `ConversionBlock` caveat apparatus and deserve their own increment (§2.1) |
| **D9** | Chart geometry lives in `apps/web/charts.py`, not in the views | `routes.py` already carries three pages in ~300 lines, and pure functions are what make the geometry testable (§3) |

Decisions D3 (views call repositories, not the application's own HTTP API) and
D4 (Pydantic schemas are the shape handed to templates) of the catalog-browser
design carry over unchanged and are not restated here.

## 9. Out of scope

* **Interactivity of any kind** — hover tooltips, zoom, drag-to-select a range.
  Adding it to a served SVG later is additive; dismantling a SPA is not.
* **One country across N indicators**, which would require base-100
  normalisation (D2).
* **Exporting the chart as an image.** The CSV export already exists at
  `/api/v1/observations/export.csv`.
* **Caching series.** Optimisation with no measurement asking for it.
* **Authentication and rate limiting.** v0.5.0's concern.
