"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { Map as MapLibreMap, GeoJSONSource } from "maplibre-gl";
import type * as GeoJSON from "geojson";
import { MapLibreWrapper } from "@/components/map/MapLibreWrapper";
import { MapControls } from "@/components/map/MapControls";
import { MapDetailCard } from "@/components/map/MapDetailCard";
import { useIndicators, useBoundaries, useObservations } from "@/hooks/useReimApi";
import { computeChoroplethScale } from "@/lib/choropleth";
import { GeoBoundariesCollection } from "@/types/api";

const PANAMA_PROVINCES: Record<string, string> = {
  "01": "Bocas del Toro",
  "02": "Coclé",
  "03": "Colón",
  "04": "Chiriquí",
  "05": "Darién",
  "06": "Herrera",
  "07": "Los Santos",
  "08": "Panamá",
  "09": "Veraguas",
  "13": "Panamá Oeste",
};

const COUNTRY_NAMES: Record<string, string> = {
  NI: "Nicaragua",
  GT: "Guatemala",
  SV: "El Salvador",
  HN: "Honduras",
  CR: "Costa Rica",
  PA: "Panamá",
  BZ: "Belice",
};

export default function MapPage() {
  const [level, setLevel] = useState<"country" | "administrative_area">("country");
  const [selectedIndicatorCode, setSelectedIndicatorCode] = useState<string>("");
  const [selectedPeriod, setSelectedPeriod] = useState<string>("");
  const [selectedFeature, setSelectedFeature] = useState<{
    name: string;
    value: number | null | undefined;
  } | null>(null);
  const [mapInstance, setMapInstance] = useState<MapLibreMap | null>(null);

  const { data: indicators = [], isLoading: isIndLoading } = useIndicators();
  const { data: boundaries } = useBoundaries(level);

  // Auto-select first indicator
  const activeIndicatorCode = selectedIndicatorCode || indicators[0]?.code || "";
  const selectedIndicator = indicators.find((i) => i.code === activeIndicatorCode);

  const { data: observations = [] } = useObservations(activeIndicatorCode);

  // Filter observations matching current geographic level
  const filteredObs = useMemo(() => {
    return observations.filter((o) => {
      if (level === "country") {
        return !o.administrative_area_code;
      }
      return Boolean(o.administrative_area_code);
    });
  }, [observations, level]);

  // Derived periods list
  const periods = useMemo(() => {
    const set = new Set<string>();
    filteredObs.forEach((o) => {
      if (o.period_label) set.add(o.period_label);
    });
    return Array.from(set).sort().reverse();
  }, [filteredObs]);

  const activePeriod = selectedPeriod || periods[0] || "";

  // Map observation values for active period
  const valueMap = useMemo(() => {
    const map = new Map<string, number | null>();
    filteredObs.forEach((o) => {
      if (o.period_label === activePeriod) {
        const key = level === "country" ? o.country_iso2 : o.administrative_area_code;
        if (key) {
          map.set(key, o.value_numeric);
        }
      }
    });
    return map;
  }, [filteredObs, activePeriod, level]);

  // Values array for scale
  const numericValues = useMemo(() => {
    const vals: number[] = [];
    valueMap.forEach((v) => {
      if (typeof v === "number" && !isNaN(v)) vals.push(v);
    });
    return vals;
  }, [valueMap]);

  const scale = useMemo(() => computeChoroplethScale(numericValues), [numericValues]);

  // Enriched GeoJSON features
  const enrichedGeoJson = useMemo<GeoBoundariesCollection | null>(() => {
    if (!boundaries) return null;

    const features = boundaries.features.map((f) => {
      const key =
        level === "country"
          ? (f.properties.iso2 ?? "")
          : (f.properties.code ?? "");
      const name =
        level === "country"
          ? COUNTRY_NAMES[key] || f.properties.name || key
          : PANAMA_PROVINCES[key] || f.properties.name || key;
      const val = valueMap.get(key);
      const fillColor = scale.getColor(val);

      return {
        ...f,
        properties: {
          ...f.properties,
          name,
          value: val,
          fillColor,
        },
      };
    });

    return {
      type: "FeatureCollection",
      features,
    };
  }, [boundaries, level, valueMap, scale]);

  const onMapLoaded = useCallback((map: MapLibreMap) => {
    setMapInstance(map);
  }, []);

  // Pan/zoom adjustment on level switch
  useEffect(() => {
    if (!mapInstance) return;
    if (level === "administrative_area") {
      mapInstance.flyTo({ center: [-80.5, 8.5], zoom: 6.8, essential: true });
    } else {
      mapInstance.flyTo({ center: [-85.5, 12.8], zoom: 5.2, essential: true });
    }
  }, [level, mapInstance]);

  // Sync layer data with map
  useEffect(() => {
    if (!mapInstance || !enrichedGeoJson) return;

    const sourceId = "reim-boundaries";
    const fillLayerId = "reim-boundaries-fill";
    const lineLayerId = "reim-boundaries-line";

    const source = mapInstance.getSource(sourceId) as GeoJSONSource | undefined;
    if (!source) {
      mapInstance.addSource(sourceId, {
        type: "geojson",
        data: enrichedGeoJson as GeoJSON.FeatureCollection,
      });

      mapInstance.addLayer({
        id: fillLayerId,
        type: "fill",
        source: sourceId,
        paint: {
          "fill-color": ["get", "fillColor"],
          "fill-opacity": 0.8,
        },
      });

      mapInstance.addLayer({
        id: lineLayerId,
        type: "line",
        source: sourceId,
        paint: {
          "line-color": "#e8b84b",
          "line-width": 1.2,
          "line-opacity": 0.9,
        },
      });

      mapInstance.on("click", fillLayerId, (e) => {
        const feature = e.features?.[0];
        if (feature?.properties) {
          setSelectedFeature({
            name: feature.properties.name || "Territorio",
            value: feature.properties.value ?? null,
          });
        }
      });

      mapInstance.on("mouseenter", fillLayerId, () => {
        mapInstance.getCanvas().style.cursor = "pointer";
      });

      mapInstance.on("mouseleave", fillLayerId, () => {
        mapInstance.getCanvas().style.cursor = "";
      });
    } else {
      source.setData(enrichedGeoJson);
    }
  }, [mapInstance, enrichedGeoJson]);

  return (
    <div className="relative h-[calc(100vh-3.5rem)] w-full overflow-hidden bg-reim-bg">
      <MapLibreWrapper onMapLoaded={onMapLoaded}>
        {!isIndLoading && indicators.length > 0 && (
          <MapControls
            indicators={indicators}
            selectedIndicatorId={activeIndicatorCode}
            onSelectIndicator={(code) => {
              setSelectedIndicatorCode(code);
              setSelectedPeriod("");
              setSelectedFeature(null);
            }}
            level={level}
            onSelectLevel={(lvl) => {
              setLevel(lvl);
              setSelectedPeriod("");
              setSelectedFeature(null);
            }}
            periods={periods}
            selectedPeriod={activePeriod}
            onSelectPeriod={setSelectedPeriod}
          />
        )}

        {selectedFeature && (
          <MapDetailCard
            name={selectedFeature.name}
            value={selectedFeature.value}
            unit={selectedIndicator?.unit}
            period={activePeriod}
            indicator={selectedIndicator}
            onClose={() => setSelectedFeature(null)}
          />
        )}

        {/* Legend */}
        {numericValues.length > 0 && (
          <div className="absolute bottom-6 left-4 z-10 rounded-xl border border-reim-border bg-reim-surface/90 px-3 py-2 shadow-lg backdrop-blur-md">
            <div className="text-[10px] font-bold uppercase tracking-wider text-reim-subtle">
              Escala ({selectedIndicator?.unit || ""})
            </div>
            <div className="mt-1.5 flex items-center gap-1">
              <span className="text-[10px] font-mono text-reim-muted">
                {scale.min.toLocaleString()}
              </span>
              <div className="flex h-2.5 w-24 overflow-hidden rounded border border-reim-borderSubtle">
                <div className="h-full flex-1 bg-[#1e293b]" />
                <div className="h-full flex-1 bg-[#5a451d]" />
                <div className="h-full flex-1 bg-[#9b752b]" />
                <div className="h-full flex-1 bg-[#e8b84b]" />
              </div>
              <span className="text-[10px] font-mono text-reim-gold">
                {scale.max.toLocaleString()}
              </span>
            </div>
          </div>
        )}
      </MapLibreWrapper>
    </div>
  );
}
