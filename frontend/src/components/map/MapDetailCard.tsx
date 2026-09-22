"use client";

import { Indicator } from "@/types/api";

interface MapDetailCardProps {
  name: string;
  value?: number | null;
  unit?: string | null;
  currency?: string | null;
  period?: string;
  indicator?: Indicator;
  onClose: () => void;
}

export function MapDetailCard({
  name,
  value,
  unit,
  currency,
  period,
  indicator,
  onClose,
}: MapDetailCardProps) {
  return (
    <div className="absolute right-4 top-4 z-10 w-72 rounded-xl border border-reim-border bg-reim-surface/95 p-4 shadow-xl backdrop-blur-md">
      <div className="flex items-start justify-between">
        <div>
          <span className="text-[10px] font-bold text-reim-gold uppercase tracking-wider">
            Territorio
          </span>
          <h3 className="text-base font-bold text-reim-text">{name}</h3>
        </div>
        <button
          onClick={onClose}
          className="text-reim-subtle hover:text-reim-text p-1 text-sm font-bold rounded hover:bg-reim-bg"
          aria-label="Cerrar detalle"
        >
          ✕
        </button>
      </div>

      <div className="mt-3 border-t border-reim-borderSubtle pt-3">
        <div className="text-xs text-reim-muted line-clamp-1">{indicator?.name || "Valor"}</div>
        <div className="mt-1 text-2xl font-extrabold text-reim-gold font-mono">
          {value !== null && value !== undefined ? value.toLocaleString() : "Sin datos"}
          {currency && <span className="ml-1 text-xs text-reim-subtle font-normal">{currency}</span>}
          {unit && !currency && <span className="ml-1 text-xs text-reim-subtle font-normal">{unit}</span>}
        </div>
        {period && (
          <div className="mt-2 text-[11px] text-reim-subtle">
            Período: <span className="font-mono text-reim-muted">{period}</span>
          </div>
        )}
        {indicator?.description && (
          <p className="mt-2 text-[11px] text-reim-subtle line-clamp-3">
            {indicator.description}
          </p>
        )}
      </div>
    </div>
  );
}
