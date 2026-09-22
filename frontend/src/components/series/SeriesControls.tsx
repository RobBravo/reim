"use client";

import { FormEvent, useState } from "react";
import { Country, Indicator } from "@/types/api";

export interface SeriesSelection {
  indicator: string;
  countries: string[];
  dateFrom?: string;
  dateTo?: string;
}

interface SeriesControlsProps {
  indicators: Indicator[];
  countries: Country[];
  initialIndicator?: string;
  initialCountries?: string[];
  initialDateFrom?: string;
  initialDateTo?: string;
  pending?: boolean;
  onSubmit: (selection: SeriesSelection) => void;
}

export function SeriesControls({ indicators, countries, initialIndicator = "", initialCountries = [], initialDateFrom = "", initialDateTo = "", pending = false, onSubmit }: SeriesControlsProps) {
  const [indicator, setIndicator] = useState(initialIndicator);
  const [selectedCountries, setSelectedCountries] = useState(initialCountries);
  const [dateFrom, setDateFrom] = useState(initialDateFrom);
  const [dateTo, setDateTo] = useState(initialDateTo);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit({ indicator, countries: selectedCountries, ...(dateFrom ? { dateFrom } : {}), ...(dateTo ? { dateTo } : {}) });
  }

  return (
    <form onSubmit={submit} className="grid gap-4 rounded-xl border border-reim-border bg-reim-surface p-4 sm:grid-cols-2 lg:grid-cols-5">
      <label className="text-sm text-reim-muted">
        Indicador
        <select required value={indicator} onChange={(event) => setIndicator(event.target.value)} className="mt-1 w-full rounded-md border border-reim-border bg-reim-bg px-3 py-2 text-reim-text">
          <option value="">Selecciona un indicador</option>
          {indicators.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
        </select>
      </label>
      <label className="text-sm text-reim-muted sm:col-span-2">
        Países (Ctrl/Cmd para elegir varios)
        <select required multiple value={selectedCountries} onChange={(event) => setSelectedCountries(Array.from(event.target.selectedOptions, (option) => option.value))} className="mt-1 min-h-24 w-full rounded-md border border-reim-border bg-reim-bg px-3 py-2 text-reim-text">
          {countries.filter((country) => country.is_active).map((country) => <option key={country.iso3} value={country.iso3}>{country.name}</option>)}
        </select>
      </label>
      <label className="text-sm text-reim-muted">
        Desde
        <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="mt-1 w-full rounded-md border border-reim-border bg-reim-bg px-3 py-2 text-reim-text" />
      </label>
      <label className="text-sm text-reim-muted">
        Hasta
        <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="mt-1 w-full rounded-md border border-reim-border bg-reim-bg px-3 py-2 text-reim-text" />
      </label>
      <div className="sm:col-span-2 lg:col-span-5">
        <button type="submit" disabled={pending || !indicator || selectedCountries.length === 0} className="rounded-md bg-reim-gold px-4 py-2 font-semibold text-reim-bg disabled:opacity-50">{pending ? "Cargando…" : "Consultar series"}</button>
      </div>
    </form>
  );
}
