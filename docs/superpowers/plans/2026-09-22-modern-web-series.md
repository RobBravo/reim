# Modern Web Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the interim `/legacy/series` link with a statically exported `/series/` page that charts the existing comparison API without changing its contract.

**Architecture:** Add a typed client for `GET /api/v1/compare`, a React Query hook, accessible chart and selector components, and a client-rendered Next page. Keep selection in the URL query string, never downsample, and use the API's `comparable` and `levels_comparable` flags to choose one shared chart or per-country small multiples.

**Tech Stack:** Next.js 15 static export, React 19, TypeScript, TanStack Query, `lightweight-charts`, Vitest, React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-21-modern-web-frontend-design.md` §§5–7; chart behavior and state requirements in `docs/superpowers/specs/2026-09-12-time-series-dashboard-design.md` §§2–7.

## Approved Security Scope Extension

On 2026-09-22, the user approved updating the existing audited dependencies in addition to adding the chart library: `maplibre-gl` to `6.10.0`, and `next` plus `eslint-config-next` to `16.3.6`. The baseline audit found MapLibre's critical XSS advisory and a high-severity vulnerable PostCSS nested under Next 15.5.25. Next 16 removes `next lint`; change the package script to run ESLint directly. Keep React 19 and Node 20 builder compatibility, and verify the static export under Next 16. Moderate Vitest findings are outside this approved extension and must be reported if still present.

## Global Constraints

- Do not change `apps/api` or its JSON contract.
- Query one indicator across selected countries; do not implement one country across multiple indicators.
- Overlay only when both `comparable` and `levels_comparable` are true; otherwise use small multiples.
- Do not draw a country's line if that country's `units` has more than one entry; name the units and retain the series metadata in the page.
- Do not convert currencies, downsample, smooth or silently truncate observations.
- Request at most 1,500 periods; when more match, state the actual count and ask for a narrower date range.
- Keep the page usable with explicit loading, first-visit, empty, partial-data, invalid-selection, API-error and over-limit states.
- Use the existing dark REIM palette, shared header and responsive layout.
- Keep static export: no server-side fetching, Next.js API route or runtime Node server.
- Keep critical/high dependency audit findings at zero after the approved MapLibre and Next upgrades; report remaining moderate findings.

## Review Focus

- A date interval containing more than 1,500 periods must show the cap and actual count without drawing a truncated chart; test via mocked `meta.total`.
- Comparable units but `levels_comparable: false` must produce independent country charts; test that no shared-chart component is rendered.
- A country with multiple units must be excluded from chart lines and explicitly identified; test this alongside another drawable country.
- A requested country with no data must remain named when other countries do have data; test null values and summary counts.
- Invalid indicator/country codes and database/API failures must be distinguishable from a valid selection with no observations; test 404 and rejected query states separately.

---

## File Structure

- Modify `frontend/package.json` and `frontend/package-lock.json`: add the already-approved chart library dependency and retain existing scripts.
- Modify `frontend/src/types/api.ts`: define the typed comparison response matching `reim/schemas/comparison.py`.
- Modify `frontend/src/lib/api.ts`: add a comparison request with repeated `country` parameters, optional dates and a 1,500-period cap across bounded pages.
- Modify `frontend/src/hooks/useReimApi.ts`: expose a query keyed by indicator, countries and date range; disable it until the selection is valid.
- Create `frontend/src/components/series/SeriesControls.tsx`: accessible indicator/country/date selection and submit behavior.
- Create `frontend/src/components/series/SeriesChart.tsx`: render one shared line chart or one chart per country, with cleanup for chart instances and accessible textual equivalents.
- Create `frontend/src/app/series/page.tsx`: own URL selection, data states, comparability decisions, unit-change handling and the value table.
- Modify `frontend/src/components/Header.tsx`: point Series to `/series/` and remove interim-link behavior only for that item.
- Create focused tests under `frontend/src/lib/__tests__/api.test.ts`, `frontend/src/hooks/__tests__/useComparison.test.ts`, `frontend/src/components/series/__tests__/`, `frontend/src/app/series/__tests__/` as appropriate to existing test conventions.
- Modify `frontend/src/components/__tests__/Header.test.tsx`: assert the final `/series/` route.

### Task 1: Add comparison response types, client call and query hook

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/__tests__/api.test.ts`
- Modify: `frontend/src/hooks/useReimApi.ts`
- Test: `frontend/src/hooks/__tests__/useComparison.test.tsx`

**Interfaces:**
- Produces `ComparisonResponse`, `ComparisonRow`, `ComparisonSeries`, and `ComparisonIndicator` types matching the API schema.
- Produces `reimApi.getComparison({indicator_code, countries, date_from?, date_to?})` and `useComparison(...)`.
- Request query parameters are `indicator`, repeated `country`, optional `date_from`/`date_to`, `order=asc`, `limit=1500`, and `offset` for bounded pagination. The API may cap `limit` to its configured `REIM_MAX_PAGE_SIZE` (default 1,000), so the client must follow `meta.limit` and `meta.returned` when `meta.total <= 1,500`.

- [x] **Step 1: Write API request tests**

Assert the requested URL contains the indicator, repeated ISO country values, optional date bounds, `order=asc`, `limit=1500`, and the requested offset; assert omitted dates are not serialized. Mock two API pages where the first page's actual `meta.limit` is 1,000 and `meta.total` is 1,200, then assert the client requests offset 1,000 and merges all 1,200 periods in order. Also assert a non-success status rejects with its status in the error and a zero-progress page rejects instead of looping.

- [x] **Step 2: Run the focused test and confirm failure**

Run: `cd frontend && npx vitest run src/lib/__tests__/api.test.ts`
Expected: the new comparison request tests fail because `getComparison` is not defined.

- [x] **Step 3: Add exact comparison types and API function**

Match the response schema: metadata, indicator code/name/frequency, both comparability booleans, notes, per-country summaries (`units`, `currency_codes`, `observations`, period bounds), and aligned rows (`period_label`, `values`). Model nullable values explicitly. Do not add conversion fields to the request or UI. `getComparison` fetches the first page with `limit=1500`; if `meta.total <= 1500`, it follows pages using the server-returned `meta.limit` and the next `offset` until all periods are present. If the total exceeds 1,500, return the first response and its total so the page can show the over-limit state without pretending the truncated data is complete. Fail clearly if a page reports zero returned rows while `offset < total`.

- [x] **Step 4: Run the focused API tests**

Run: `cd frontend && npx vitest run src/lib/__tests__/api.test.ts`
Expected: all API client tests pass.

- [x] **Step 5: Write hook tests and confirm they fail**

Test key separation for differing date ranges and disabled behavior with no selection using the existing `QueryClientProvider` test setup. Run: `cd frontend && npx vitest run src/hooks/__tests__/useComparison.test.tsx`. Expected: tests fail because `useComparison` is not defined.

- [x] **Step 6: Implement `useComparison` and run API/hook tests**

Use `useQuery` with a query key containing every input; do not issue a request unless indicator and at least one country are selected.

Run: `cd frontend && npx vitest run src/lib/__tests__/api.test.ts src/hooks/__tests__/useComparison.test.tsx`
Expected: all focused tests pass.

### Task 2: Build the accessible selection controls and chart wrapper

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`
- Create: `frontend/src/components/series/SeriesControls.tsx`
- Create: `frontend/src/components/series/SeriesChart.tsx`
- Create: tests alongside those components under `frontend/src/components/series/__tests__/`

**Interfaces:**
- `SeriesControls` receives indicator/country lists, selection values, pending state and an `onSubmit` callback with indicator, ISO-3 country list and optional date strings.
- `SeriesChart` receives one panel title, country labels and ordered `{time, value}` points; it owns and disposes its `lightweight-charts` instance.

- [x] **Step 1: Update the approved dependencies, add charts and write controls tests**

Run `npm install lightweight-charts@5.2.1 maplibre-gl@6.10.0 next@16.3.6` and `npm install --save-dev eslint-config-next@16.3.6`. Update the `lint` package script from the removed `next lint` command to `eslint .`. Keep `node:20-alpine` in `deploy/Dockerfile.frontend`; Next 16 requires Node 20.9+, and the image's Node 20 LTS tag meets that floor. Run `npm audit --json` and confirm the MapLibre critical advisory and Next/PostCSS high advisory are gone; retain any remaining moderate findings for the final report. Test accessible labels, multi-country selection, date values and submit output.

- [x] **Step 2: Run the controls tests and confirm failure**

Run: `cd frontend && npx vitest run src/components/series/__tests__/SeriesControls.test.tsx`
Expected: test fails because the component is not present.

- [x] **Step 3: Implement responsive accessible controls**

Use native labeled select/input controls and a submit button. Preserve submitted selections through the page URL. Do not auto-submit on every keystroke or offer currency conversion.

- [x] **Step 4: Run the controls tests**

Run: `cd frontend && npx vitest run src/components/series/__tests__/SeriesControls.test.tsx`
Expected: all controls tests pass.

- [x] **Step 5: Write chart lifecycle and content tests**

Mock the chart library boundary to verify that each panel creates one chart, adds the expected series and removes the chart on unmount. Assert the panel heading and a textual data table/description remain available without reading canvas pixels.

- [x] **Step 6: Implement the chart wrapper and run its tests**

Create the chart after mount, update its data/options when props change, and remove it in effect cleanup. Format labels from API `period_label`/date values without changing numeric observations. Do not use interpolation or downsampling.

Run: `cd frontend && npx vitest run src/components/series/__tests__/`
Expected: all series component tests pass.

### Task 3: Implement `/series/` with selection, URL state and all result states

**Files:**
- Create: `frontend/src/app/series/page.tsx`
- Create: `frontend/src/app/series/__tests__/page.test.tsx`
- Modify: `frontend/src/types/api.ts` only if an API field is missing from Task 1.

**Interfaces:**
- Reads `indicator`, repeated `country`, `date_from`, and `date_to` from Next search parameters. Because static export cannot resolve request-specific parameters during build, put the `useSearchParams` consumer under a React `Suspense` boundary and keep the page itself statically exportable.
- Uses `useIndicators`, `useCountries`, and `useComparison`; chart inputs are derived from `ComparisonResponse.data` without changing or dropping table values.

- [x] **Step 1: Write page-state tests**

Cover first visit, indicator/country loading, inverted date range, API failure, API 404 for an invalid selection, valid selection with no data, partial country coverage, comparable overlay, `levels_comparable=false` small multiples, unit-changing country excluded from chart, and more than 1,500 matching periods.

- [x] **Step 2: Run page tests and confirm failure**

Run: `cd frontend && npx vitest run src/app/series/__tests__/page.test.tsx`
Expected: tests fail because `/series/page.tsx` is not present.

- [x] **Step 3: Implement URL-driven selection and loading/error states**

Submit controls to `/series/?indicator=...&country=...`; keep a first-visit explanation before a selection. Show loading status while catalog or comparison data is loading. Render invalid selection separately from service failure and from no observations.

- [x] **Step 4: Implement data, comparability and volume rendering**

When both comparability flags are true, render one shared chart for drawable countries. Otherwise, render one chart per drawable country and all API comparability notes. A series with `units.length > 1` gets no chart line and receives an explicit explanation naming its units. Keep missing countries named. If `meta.total > 1500`, show the actual count and date-range guidance; never chart the first 1,500 as though complete. Render published values in an accessible table with country, period and value.

- [x] **Step 5: Run page tests and adjust until green**

Run: `cd frontend && npx vitest run src/app/series/__tests__/page.test.tsx`
Expected: all eleven listed page-state and comparability cases pass.

### Task 4: Switch navigation, run frontend quality gates and review

**Files:**
- Modify: `frontend/src/components/Header.tsx`
- Modify: `frontend/src/components/__tests__/Header.test.tsx`

- [x] **Step 1: Update the navigation regression test**

Change the expected Series destination to `/series/`; verify the Operations item still uses its existing interim route.

- [x] **Step 2: Point Series navigation at the static route**

Use `next/link` for `/series/`, remove only the Series-specific interim comment/branching if it is no longer used, and leave Operations untouched.

- [x] **Step 3: Run all frontend checks**

Run:

```bash
cd frontend
npm run typecheck
npx eslint .
npm test
npm run build
```

Expected: all commands exit 0 and static export contains the `/series/` route.

- [x] **Step 4: Review the complete diff**

Confirm no API, database, deployment or legacy implementation files changed; verify API URL parameters, chart cleanup, URL-restorable selection, no conversion/downsampling, all states, and the unchanged `/legacy/runs` navigation. Confirm the Node 20 builder meets Next 16's 20.9 minimum, lint uses ESLint CLI, and critical/high audit counts are zero. Report any mismatch before considering release.

## Spec coverage check

- Static client-side route, shared header and API-only data flow: Tasks 1, 3 and 4.
- `lightweight-charts`, interactive chart lifecycle and responsive selection: Task 2.
- Overlay/small multiples, unit changes, missing data, error/empty/loading states and 1,500-period cap: Task 3.
- Accessible equivalent values and presentation without changing published figures: Task 2 and Task 3.
- Automated checks equivalent to the frontend CI gate: Task 4.

## Execution boundary

This plan does not authorize implementation, dependency installation, commit, deployment, or changes to the already modified deployment documentation files. Before implementation, select an execution method and obtain write approval for the plan's frontend file scope. Commit and deployment each require separate approval after review.
