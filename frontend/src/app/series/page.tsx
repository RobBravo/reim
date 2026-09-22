"use client";

import { Suspense, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SeriesChart, ChartLine } from "@/components/series/SeriesChart";
import { SeriesControls } from "@/components/series/SeriesControls";
import { useComparison, useCountries, useIndicators } from "@/hooks/useReimApi";

const COLORS = ["#e6b84c", "#38bdf8", "#f472b6", "#4ade80", "#fb7185", "#a78bfa", "#f97316"];

function SeriesContent() {
  const router = useRouter();
  const search = useSearchParams();
  const indicatorCode = search.get("indicator") ?? "";
  const countryCodes = search.getAll("country");
  const dateFrom = search.get("date_from") ?? "";
  const dateTo = search.get("date_to") ?? "";
  const invalidDateRange = Boolean(dateFrom && dateTo && dateFrom > dateTo);
  const indicatorsQuery = useIndicators();
  const countriesQuery = useCountries();
  const indicators = indicatorsQuery.data ?? [];
  const countries = countriesQuery.data ?? [];
  const comparison = useComparison(invalidDateRange ? undefined : indicatorCode, countryCodes, dateFrom || undefined, dateTo || undefined);
  const selected = Boolean(indicatorCode && countryCodes.length);
  const invalidIndicator = selected && !indicatorsQuery.isLoading && !indicators.some((item) => item.code === indicatorCode);
  const invalidCountries = selected && !countriesQuery.isLoading && countryCodes.some((code) => !countries.some((item) => item.iso3 === code));

  const linesByCountry = useMemo(() => {
    const response = comparison.data;
    if (!response) return [] as Array<{ country: string; line: ChartLine }>;
    return response.series.flatMap((series, index) => {
      if (series.units.length !== 1) return [];
      const points = response.data.flatMap((row) => {
        const value = row.values[series.country_iso3];
        return value === null || value === undefined ? [] : [{ time: row.period_start as `${number}-${number}-${number}`, value }];
      });
      return points.length ? [{ country: series.country_iso3, line: { name: series.country_name, color: COLORS[index % COLORS.length], points } }] : [];
    });
  }, [comparison.data]);

  function submit(selection: { indicator: string; countries: string[]; dateFrom?: string; dateTo?: string }) {
    const params = new URLSearchParams();
    params.set("indicator", selection.indicator);
    selection.countries.forEach((country) => params.append("country", country));
    if (selection.dateFrom) params.set("date_from", selection.dateFrom);
    if (selection.dateTo) params.set("date_to", selection.dateTo);
    router.push(`/series/?${params.toString()}`);
  }

  return <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
    <header><h1 className="text-3xl font-bold text-reim-text">Series comparativas</h1><p className="mt-2 text-reim-muted">Compara la evolución de un indicador entre países. Las observaciones publicadas se conservan sin suavizado ni conversión.</p></header>
    {(indicatorsQuery.isLoading || countriesQuery.isLoading) ? <p role="status">Cargando indicadores y países…</p> : indicatorsQuery.isError || countriesQuery.isError ? <p role="alert">No se pudieron cargar los catálogos. Intenta nuevamente más tarde.</p> : <SeriesControls key={`${indicatorCode}:${countryCodes.join(",")}:${dateFrom}:${dateTo}`} indicators={indicators} countries={countries} initialIndicator={indicatorCode} initialCountries={countryCodes} initialDateFrom={dateFrom} initialDateTo={dateTo} pending={comparison.isFetching} onSubmit={submit} />}
    {!selected && <p className="rounded-lg border border-reim-border bg-reim-surface p-4 text-reim-muted">Elige un indicador y uno o más países para consultar sus series.</p>}
    {selected && invalidDateRange && <p role="alert" className="rounded-lg border border-amber-500/40 bg-reim-surface p-4">La fecha inicial debe ser anterior o igual a la fecha final.</p>}
    {selected && (invalidIndicator || invalidCountries) && <p role="alert" className="rounded-lg border border-amber-500/40 bg-reim-surface p-4">La selección contiene {invalidIndicator ? "un indicador" : ""}{invalidIndicator && invalidCountries ? " y " : ""}{invalidCountries ? "uno o más países" : ""} no válidos.</p>}
    {selected && !invalidDateRange && !invalidIndicator && !invalidCountries && comparison.isLoading && <p role="status">Cargando observaciones…</p>}
    {comparison.isError && !invalidDateRange && !invalidIndicator && !invalidCountries && <p role="alert" className="rounded-lg border border-red-500/40 bg-reim-surface p-4">No se pudieron consultar los datos: {comparison.error.message}</p>}
    {comparison.data && !invalidDateRange && !invalidIndicator && !invalidCountries && <>
      {comparison.data.meta.total > 1500 ? <p role="alert" className="rounded-lg border border-amber-500/40 bg-reim-surface p-4">El intervalo contiene {comparison.data.meta.total.toLocaleString("es")} períodos; el máximo es 1,500. Reduce el rango de fechas para ver una serie completa.</p> : comparison.data.meta.total === 0 ? <p className="rounded-lg border border-reim-border bg-reim-surface p-4">La selección es válida, pero no hay observaciones en este intervalo.</p> : <>
        {!(comparison.data.comparable && comparison.data.levels_comparable) && comparison.data.comparability_notes.length > 0 && <aside className="rounded-lg border border-reim-border bg-reim-surface p-4 text-sm text-reim-muted"><h2 className="font-semibold text-reim-text">Notas de comparabilidad</h2><ul className="mt-2 list-disc pl-5">{comparison.data.comparability_notes.map((note) => <li key={note}>{note}</li>)}</ul></aside>}
        {comparison.data.series.filter((series) => series.units.length > 1).map((series) => <p key={series.country_iso3} className="rounded-lg border border-amber-500/40 bg-reim-surface p-3 text-sm">No se grafica {series.country_name}: la unidad cambia entre períodos ({series.units.join(", ")}). Sus valores permanecen en la tabla.</p>)}
        {comparison.data.series.filter((series) => series.observations === 0).map((series) => <p key={series.country_iso3} className="text-sm text-reim-muted">{series.country_name}: sin observaciones para esta selección.</p>)}
        {countryCodes.filter((code) => !comparison.data!.series.some((series) => series.country_iso3 === code)).map((code) => <p key={code} className="text-sm text-reim-muted">{countries.find((country) => country.iso3 === code)?.name ?? code}: sin observaciones devueltas para esta selección.</p>)}
        {linesByCountry.length > 0 && (comparison.data.comparable && comparison.data.levels_comparable
          ? <SeriesChart title={`${comparison.data.indicator.name} · ${linesByCountry.map(({ line }) => line.name).join(", ")}`} lines={linesByCountry.map(({ line }) => line)} />
          : <div className="grid gap-4 lg:grid-cols-2">{linesByCountry.map(({ country, line }) => <SeriesChart key={country} title={`${comparison.data!.indicator.name} · ${line.name}`} lines={[line]} />)}</div>)}
        {linesByCountry.length === 0 && <p className="text-reim-muted">No hay series con observaciones y unidad estable para graficar.</p>}
        <section className="overflow-x-auto rounded-xl border border-reim-border bg-reim-surface p-4"><h2 className="mb-3 font-semibold text-reim-text">Valores publicados</h2><table className="w-full text-left text-sm"><thead><tr><th className="p-2">Período</th>{comparison.data.series.map((series) => <th key={series.country_iso3} className="p-2">{series.country_name} ({series.units.join(" / ") || "unidad no informada"})</th>)}</tr></thead><tbody>{comparison.data.data.map((row) => <tr key={row.period_start} className="border-t border-reim-border"><th className="p-2 font-medium">{row.period_label}</th>{comparison.data!.series.map((series) => <td key={series.country_iso3} className="p-2">{row.values[series.country_iso3] ?? "—"}</td>)}</tr>)}</tbody></table></section>
      </>}
    </>}
  </main>;
}

export default function SeriesPage() {
  return <Suspense fallback={<main className="mx-auto max-w-7xl px-4 py-8 text-reim-muted">Cargando selección…</main>}><SeriesContent /></Suspense>;
}
