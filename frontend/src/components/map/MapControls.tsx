"use client";

import { useState } from "react";
import { Indicator } from "@/types/api";

interface MapControlsProps {
  indicators: Indicator[];
  selectedIndicatorId: string;
  onSelectIndicator: (id: string) => void;
  level: "country" | "administrative_area";
  onSelectLevel: (lvl: "country" | "administrative_area") => void;
  periods: string[];
  selectedPeriod: string;
  onSelectPeriod: (p: string) => void;
}

export function MapControls({
  indicators,
  selectedIndicatorId,
  onSelectIndicator,
  level,
  onSelectLevel,
  periods,
  selectedPeriod,
  onSelectPeriod,
}: MapControlsProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  return (
    <div className="absolute left-4 top-4 z-10 w-80 rounded-xl border border-reim-border bg-reim-surface/95 p-4 shadow-xl backdrop-blur-md">
      <div className="flex items-center justify-between pb-2 border-b border-reim-borderSubtle">
        <span className="text-xs font-bold uppercase tracking-wider text-reim-gold">
          Controles del Mapa
        </span>
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="text-xs text-reim-muted hover:text-reim-text px-1.5 py-0.5 rounded hover:bg-reim-bg"
          aria-label={isCollapsed ? "Expandir controles" : "Plegar controles"}
        >
          {isCollapsed ? "▼" : "▲"}
        </button>
      </div>

      {!isCollapsed && (
        <div className="mt-3 space-y-3">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-reim-subtle">
              Indicador
            </label>
            <select
              value={selectedIndicatorId}
              onChange={(e) => onSelectIndicator(e.target.value)}
              className="mt-1 w-full rounded-md border border-reim-border bg-reim-bg px-2.5 py-1.5 text-xs text-reim-text focus:border-reim-gold focus:outline-none"
            >
              {indicators.map((ind) => (
                <option key={ind.id} value={ind.id}>
                  {ind.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-reim-subtle">
              Nivel Geográfico
            </label>
            <div className="mt-1 flex rounded-md bg-reim-bg p-1 border border-reim-border">
              <button
                type="button"
                onClick={() => onSelectLevel("country")}
                className={`flex-1 rounded py-1 text-xs font-medium transition-colors ${
                  level === "country"
                    ? "bg-reim-surface text-reim-gold shadow border border-reim-gold/20"
                    : "text-reim-muted hover:text-reim-text"
                }`}
              >
                Nacional
              </button>
              <button
                type="button"
                onClick={() => onSelectLevel("administrative_area")}
                className={`flex-1 rounded py-1 text-xs font-medium transition-colors ${
                  level === "administrative_area"
                    ? "bg-reim-surface text-reim-gold shadow border border-reim-gold/20"
                    : "text-reim-muted hover:text-reim-text"
                }`}
              >
                Provincial (PA)
              </button>
            </div>
          </div>

          {periods.length > 0 && (
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-reim-subtle">
                Período: <span className="text-reim-text font-mono">{selectedPeriod}</span>
              </label>
              <select
                value={selectedPeriod}
                onChange={(e) => onSelectPeriod(e.target.value)}
                className="mt-1 w-full rounded-md border border-reim-border bg-reim-bg px-2.5 py-1.5 text-xs text-reim-text focus:border-reim-gold focus:outline-none font-mono"
              >
                {periods.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
