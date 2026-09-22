"use client";

import { useEffect, useRef } from "react";
import { ColorType, createChart, LineSeries, Time } from "lightweight-charts";

export interface SeriesPoint {
  time: Time;
  value: number;
}

export interface ChartLine {
  name: string;
  color: string;
  points: SeriesPoint[];
}

interface SeriesChartProps {
  title: string;
  lines: ChartLine[];
}

export function SeriesChart({ title, lines }: SeriesChartProps) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#17212b" }, textColor: "#cbd5e1" },
      grid: { vertLines: { color: "#263442" }, horzLines: { color: "#263442" } },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155", timeVisible: true },
    });
    chartRef.current = chart;
    for (const line of lines) {
      chart.addSeries(LineSeries, { color: line.color, title: line.name, lineWidth: 2 }).setData(line.points);
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [lines]);

  return <section className="rounded-xl border border-reim-border bg-reim-surface p-4" aria-label={title}>
    <h3 className="mb-3 font-semibold text-reim-text">{title}</h3>
    <div ref={host} className="h-80 w-full" role="img" aria-label={`Gráfico de ${title}`} />
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-reim-muted">{lines.map((line) => <li key={line.name}><span style={{ color: line.color }}>●</span> {line.name}</li>)}</ul>
  </section>;
}
