"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useRun, useRuns } from "@/hooks/useReimApi";
import type { PipelineRun, PipelineRunDetail } from "@/types/api";

const STATUS_LABELS: Record<string, string> = {
  running: "En ejecución",
  success: "Correcta",
  partial: "Parcial",
  failed: "Fallida",
  skipped: "Omitida",
};

const CHECK_STATUS_LABELS: Record<string, string> = {
  passed: "Aprobada",
  failed: "Fallida",
  skipped: "Omitida",
};

const SEVERITY_LABELS: Record<string, string> = {
  info: "Informativa",
  warning: "Advertencia",
  error: "Error",
  critical: "Crítica",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("es-NI", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatDuration(value: number | null): string {
  if (value === null) return "—";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toLocaleString("es-NI", { maximumFractionDigits: 2 })} s`;
}

function RunRow({ run }: { run: PipelineRun }) {
  return <tr className="border-b border-reim-border last:border-0 align-top">
    <td className="p-3 text-reim-muted"><time dateTime={run.started_at}>{formatDate(run.started_at)}</time></td>
    <th scope="row" className="p-3 font-medium text-reim-text">{run.pipeline_key}</th>
    <td className="p-3 text-reim-muted">{STATUS_LABELS[run.status] ?? run.status}</td>
    <td className="p-3 text-reim-muted">{formatDuration(run.duration_ms)}</td>
    <td className="p-3 text-reim-muted">{run.records_inserted} / {run.records_updated} / {run.records_rejected}</td>
    <td className="p-3"><Link className="text-reim-gold underline underline-offset-2" href={`/runs/?id=${encodeURIComponent(run.id)}`}>Ver detalle</Link></td>
  </tr>;
}

function RunHistory() {
  const query = useRuns();
  if (query.isLoading) return <p role="status" className="rounded-lg border border-reim-border bg-reim-surface p-4 text-reim-muted">Cargando historial de ejecuciones…</p>;
  if (query.isError) return <p role="alert" className="rounded-lg border border-red-500/40 bg-reim-surface p-4">No se pudo consultar el historial: {query.error.message}</p>;
  if (!query.data || query.data.meta.total === 0) return <p className="rounded-lg border border-reim-border bg-reim-surface p-4 text-reim-muted">Ninguna ejecución registrada todavía.</p>;
  if (query.data.data.length === 0) return <p role="alert" className="rounded-lg border border-amber-500/40 bg-reim-surface p-4">La API informó ejecuciones, pero no devolvió filas para mostrar.</p>;

  return <>
    <p className="text-sm text-reim-muted">Mostrando {query.data.data.length} de las 100 ejecuciones más recientes ({query.data.meta.total.toLocaleString("es-NI")} en total).</p>
    <div className="overflow-x-auto rounded-xl border border-reim-border bg-reim-surface">
      <table className="w-full min-w-[760px] text-left text-sm">
        <caption className="p-3 text-left font-semibold text-reim-text">Ejecuciones recientes</caption>
        <thead className="border-y border-reim-border bg-reim-bg/60 text-xs uppercase tracking-wide text-reim-muted">
          <tr><th scope="col" className="p-3">Inicio</th><th scope="col" className="p-3">Proceso</th><th scope="col" className="p-3">Estado</th><th scope="col" className="p-3">Duración</th><th scope="col" className="p-3">Registros insertados / actualizados / rechazados</th><th scope="col" className="p-3">Detalle</th></tr>
        </thead>
        <tbody>{query.data.data.map((run) => <RunRow key={run.id} run={run} />)}</tbody>
      </table>
    </div>
  </>;
}

function MetadataRows({ run }: { run: PipelineRunDetail }) {
  const entries = Object.entries(run.run_metadata);
  if (entries.length === 0) return null;
  return <section className="space-y-3 rounded-xl border border-reim-border bg-reim-surface p-4">
    <h2 className="text-lg font-semibold text-reim-text">Metadatos de la ejecución</h2>
    <dl className="grid gap-3 sm:grid-cols-2">{entries.map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-xs uppercase tracking-wide text-reim-muted">{key}</dt><dd className="mt-1 break-words text-sm text-reim-text">{typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>
  </section>;
}

function RunDetail({ runId }: { runId: string }) {
  const query = useRun(runId);
  if (query.isLoading) return <p role="status" className="rounded-lg border border-reim-border bg-reim-surface p-4 text-reim-muted">Cargando detalle de la ejecución…</p>;
  if (query.isError) {
    const notFound = /API Error (404|422)/.test(query.error.message);
    return <p role="alert" className="rounded-lg border border-red-500/40 bg-reim-surface p-4">{notFound ? "No se encontró esa ejecución." : `No se pudo consultar el detalle: ${query.error.message}`}</p>;
  }
  const run = query.data;
  if (!run) return <p role="alert" className="rounded-lg border border-red-500/40 bg-reim-surface p-4">La API no devolvió el detalle de la ejecución.</p>;

  return <div className="space-y-6">
    <div><Link href="/runs/" className="text-sm text-reim-gold underline underline-offset-2">← Volver al historial</Link><h1 className="mt-3 break-all text-3xl font-bold text-reim-text">Detalle de ejecución</h1><p className="mt-1 text-reim-muted">{run.pipeline_key} · {STATUS_LABELS[run.status] ?? run.status}</p></div>
    {run.error_type && <section role="alert" className="space-y-2 rounded-xl border border-red-500/40 bg-reim-surface p-4"><h2 className="font-semibold text-reim-text">Error de ejecución</h2><p className="text-sm font-medium">{run.error_type}</p>{run.error_message && <p className="whitespace-pre-wrap break-words text-sm text-reim-muted">{run.error_message}</p>}</section>}
    <section className="space-y-4 rounded-xl border border-reim-border bg-reim-surface p-4">
      <h2 className="text-lg font-semibold text-reim-text">Resumen</h2>
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div><dt className="text-xs uppercase tracking-wide text-reim-muted">Inició</dt><dd className="mt-1 text-sm text-reim-text"><time dateTime={run.started_at}>{formatDate(run.started_at)}</time></dd></div>
        <div><dt className="text-xs uppercase tracking-wide text-reim-muted">Finalizó</dt><dd className="mt-1 text-sm text-reim-text">{formatDate(run.finished_at)}</dd></div>
        <div><dt className="text-xs uppercase tracking-wide text-reim-muted">Duración</dt><dd className="mt-1 text-sm text-reim-text">{formatDuration(run.duration_ms)}</dd></div>
        <div><dt className="text-xs uppercase tracking-wide text-reim-muted">Versión del conector</dt><dd className="mt-1 text-sm text-reim-text">{run.connector_version ?? "—"}</dd></div>
        <div><dt className="text-xs uppercase tracking-wide text-reim-muted">Versión del proceso</dt><dd className="mt-1 text-sm text-reim-text">{run.pipeline_version ?? "—"}</dd></div>
        <div><dt className="text-xs uppercase tracking-wide text-reim-muted">Registros (extraídos / insertados / actualizados / sin cambio / rechazados)</dt><dd className="mt-1 text-sm text-reim-text">{run.records_extracted} / {run.records_inserted} / {run.records_updated} / {run.records_unchanged} / {run.records_rejected}</dd></div>
      </dl>
    </section>
    <MetadataRows run={run} />
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-reim-text">Verificaciones de calidad ({run.quality_checks.length})</h2>
      {run.quality_checks.length === 0 ? <p className="rounded-lg border border-reim-border bg-reim-surface p-4 text-sm text-reim-muted">Esta ejecución no registró verificaciones de calidad.</p> : <div className="overflow-x-auto rounded-xl border border-reim-border bg-reim-surface"><table className="w-full min-w-[800px] text-left text-sm"><caption className="sr-only">Verificaciones de calidad</caption><thead className="border-b border-reim-border text-xs uppercase tracking-wide text-reim-muted"><tr><th scope="col" className="p-3">Verificación</th><th scope="col" className="p-3">Tipo</th><th scope="col" className="p-3">Estado</th><th scope="col" className="p-3">Severidad</th><th scope="col" className="p-3">Indicador / período</th><th scope="col" className="p-3">Esperado / observado</th></tr></thead><tbody>{run.quality_checks.map((check) => <tr key={check.id} className="border-t border-reim-border align-top"><th scope="row" className="p-3 font-medium text-reim-text">{check.check_name}</th><td className="p-3 text-reim-muted">{check.check_type}</td><td className="p-3 text-reim-muted">{CHECK_STATUS_LABELS[check.status] ?? check.status}</td><td className="p-3 text-reim-muted">{SEVERITY_LABELS[check.severity] ?? check.severity}</td><td className="p-3 text-reim-muted">{check.indicator_code ?? "—"} / {check.period_label ?? "—"}</td><td className="p-3 text-reim-muted">{check.expected_value ?? "—"} / {check.actual_value ?? "—"}</td></tr>)}</tbody></table></div>}
    </section>
  </div>;
}

function RunsContent() {
  const search = useSearchParams();
  const runId = search.get("id");
  return <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
    {!runId && <header><h1 className="text-3xl font-bold text-reim-text">Historial de operaciones</h1><p className="mt-2 max-w-3xl text-reim-muted">Consulta las ejecuciones recientes de los procesos de actualización y sus resultados.</p></header>}
    {runId ? <RunDetail runId={runId} /> : <RunHistory />}
  </main>;
}

export default function RunsPage() {
  return <Suspense fallback={<main className="mx-auto max-w-7xl px-4 py-8 text-reim-muted">Cargando historial…</main>}><RunsContent /></Suspense>;
}
