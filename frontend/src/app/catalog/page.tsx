"use client";

import { useMemo } from "react";
import { useOrganizations, usePipelineSummaries, useSources } from "@/hooks/useReimApi";
import { isRedistributable } from "@/lib/catalog";

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("es-NI", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

const STATUS_LABELS: Record<string, string> = {
  running: "En ejecución",
  success: "Correcta",
  partial: "Parcial",
  failed: "Fallida",
  skipped: "Omitida",
};

export default function CatalogPage() {
  const sourcesQuery = useSources();
  const organizationsQuery = useOrganizations();
  const pipelinesQuery = usePipelineSummaries();
  const sources = sourcesQuery.data ?? [];
  const organizationsById = useMemo(() => new Map((organizationsQuery.data ?? []).map((organization) => [organization.id, organization])), [organizationsQuery.data]);
  const pipelinesBySource = useMemo(() => new Map((pipelinesQuery.data ?? []).map((pipeline) => [pipeline.source_key, pipeline])), [pipelinesQuery.data]);

  const catalogError = sourcesQuery.error ?? organizationsQuery.error;
  const isCatalogLoading = sourcesQuery.isLoading || organizationsQuery.isLoading;

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <header>
        <h1 className="text-3xl font-bold text-reim-text">Catálogo de fuentes</h1>
        <p className="mt-2 max-w-3xl text-reim-muted">
          Consulta qué publica REIM, quién lo publica, con qué licencia y cuándo se actualizaron los datos.
        </p>
      </header>

      {isCatalogLoading && <p role="status" className="rounded-lg border border-reim-border bg-reim-surface p-4 text-reim-muted">Cargando catálogo…</p>}
      {!isCatalogLoading && catalogError && (
        <div role="alert" className="rounded-lg border border-red-500/40 bg-reim-surface p-4">
          <p>No se pudo cargar el catálogo: {catalogError.message}</p>
          <a href="/legacy" className="mt-2 inline-block font-medium text-reim-gold underline">Ver catálogo anterior</a>
        </div>
      )}

      {!isCatalogLoading && !catalogError && <>
        {pipelinesQuery.isLoading && <p role="status" className="rounded-lg border border-reim-border bg-reim-surface p-3 text-sm text-reim-muted">Cargando estado de actualización…</p>}
        {pipelinesQuery.isError && <p role="status" className="rounded-lg border border-amber-500/40 bg-reim-surface p-3 text-sm text-reim-muted">El estado de actualización no está disponible; se muestra el catálogo de fuentes.</p>}
        {sources.length === 0 && <p className="rounded-lg border border-reim-border bg-reim-surface p-4 text-reim-muted">No hay fuentes registradas en el catálogo.</p>}

        <div className="overflow-x-auto rounded-xl border border-reim-border bg-reim-surface">
          <table className="w-full min-w-[1050px] text-left text-sm">
            <caption className="p-3 text-left font-semibold text-reim-text">Fuentes de datos registradas ({sources.length})</caption>
            <thead className="border-y border-reim-border bg-reim-bg/60 text-xs uppercase tracking-wide text-reim-muted">
              <tr>
                <th scope="col" className="p-3">Fuente</th>
                <th scope="col" className="p-3">Organización</th>
                <th scope="col" className="p-3">Frecuencia</th>
                <th scope="col" className="p-3">Indicadores</th>
                <th scope="col" className="p-3">Licencia</th>
                <th scope="col" className="p-3">Último éxito</th>
                <th scope="col" className="p-3">Estado de última ejecución</th>
                <th scope="col" className="p-3">Registros (insertados / actualizados / rechazados)</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => {
                const pipeline = pipelinesBySource.get(source.source_key);
                const redistributable = isRedistributable(source.license);
                return (
                  <tr key={source.id} id={source.source_key} className="border-b border-reim-border last:border-0 align-top">
                    <th scope="row" className="p-3 font-medium text-reim-text">
                      <a href={source.documentation_url ?? source.base_url} target="_blank" rel="noreferrer" className="text-reim-gold underline decoration-reim-gold/40 underline-offset-2 hover:decoration-reim-gold">{source.name}</a>
                    </th>
                    <td className="p-3 text-reim-muted">{organizationsById.get(source.organization_id)?.name ?? "Organización no registrada"}</td>
                    <td className="p-3 text-reim-muted">{source.frequency}</td>
                    <td className="p-3 text-reim-muted">{pipelinesQuery.isError || pipelinesQuery.isLoading ? "—" : (pipeline?.indicators.length ?? 0)}</td>
                    <td className="p-3 text-reim-muted">
                      {source.license ?? "Licencia no informada"}
                      {!redistributable && <span className="ml-2 inline-flex rounded-full border border-amber-500/40 px-2 py-0.5 text-xs text-amber-300">No abierto</span>}
                    </td>
                    {pipelinesQuery.isError || pipelinesQuery.isLoading || !pipeline ? <>
                      <td className="p-3 text-reim-muted">—</td><td className="p-3 text-reim-muted">—</td><td className="p-3 text-reim-muted">—</td>
                    </> : pipeline.last_run_status === null ? <td colSpan={3} className="p-3 text-reim-muted">Nunca ejecutada</td> : <>
                      <td className="p-3 text-reim-muted"><time dateTime={pipeline.last_success_at ?? undefined}>{formatDate(pipeline.last_success_at)}</time></td>
                      <td className="p-3 text-reim-muted">{STATUS_LABELS[pipeline.last_run_status] ?? pipeline.last_run_status}</td>
                      <td className="p-3 text-reim-muted">{pipeline.records_inserted_last_run ?? "—"} / {pipeline.records_updated_last_run ?? "—"} / {pipeline.records_rejected_last_run ?? "—"}</td>
                    </>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <section className="rounded-xl border border-reim-border bg-reim-surface p-4">
          <h2 className="text-lg font-semibold text-reim-text">Fuentes deshabilitadas</h2>
          {sources.some((source) => !source.is_active) ? (
            <ul className="mt-3 space-y-2 text-sm text-reim-muted">
              {sources.filter((source) => !source.is_active).map((source) => <li key={source.id}><strong className="text-reim-text">{source.source_key}</strong> — {source.disabled_reason ?? "Motivo no informado."}</li>)}
            </ul>
          ) : <p className="mt-2 text-sm text-reim-muted">No hay fuentes deshabilitadas.</p>}
        </section>
        <p className="text-xs text-reim-muted">La clasificación de licencias abiertas reconoce únicamente CC-BY-4.0 y datos oficiales de acceso público. Si una fuente usa otros términos, revisa las condiciones del editor.</p>
      </>}
    </main>
  );
}
