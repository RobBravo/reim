"use client";

import { useEffect, useRef, useState, ReactNode } from "react";
import { addProtocol, Map as MapLibreMap, AttributionControl, NavigationControl, setWorkerUrl } from "maplibre-gl";
import { Protocol } from "pmtiles";
import "maplibre-gl/dist/maplibre-gl.css";
import { getDarkBasemapStyle } from "@/lib/map-style";

interface MapLibreWrapperProps {
  onMapLoaded?: (map: MapLibreMap) => void;
  children?: ReactNode;
}

export function MapLibreWrapper({ onMapLoaded, children }: MapLibreWrapperProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [hasWebGl, setHasWebGl] = useState(true);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    // Check WebGL availability
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (!gl) {
      // This state reports an external browser capability discovered at mount.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHasWebGl(false);
      return;
    }

    try {
      setWorkerUrl("/maplibre-gl-worker.mjs");
      const protocol = new Protocol();
      addProtocol("pmtiles", protocol.tile);

      const style = getDarkBasemapStyle("/tiles/central-america.pmtiles");

      const map = new MapLibreMap({
        container: containerRef.current,
        style,
        center: [-85.5, 12.8],
        zoom: 5.2,
        minZoom: 4,
        maxZoom: 9,
        attributionControl: false,
      });

      map.addControl(
        new AttributionControl({
          compact: true,
          customAttribution: "Contains data from geoBoundaries.org and OpenStreetMap contributors, ODbL 1.0.",
        }),
        "bottom-right"
      );

      map.addControl(new NavigationControl({ showCompass: false }), "top-right");

      map.on("load", () => {
        mapRef.current = map;
        onMapLoaded?.(map);
      });

      return () => {
        map.remove();
        mapRef.current = null;
      };
    } catch (err) {
      console.error("Map initialization failed", err);
      setHasWebGl(false);
    }
  }, [onMapLoaded]);

  return (
    <div className="relative h-full w-full overflow-hidden" data-testid="map-container">
      {!hasWebGl ? (
        <div className="flex h-full w-full items-center justify-center bg-reim-bg p-6 text-center text-reim-muted">
          <div className="max-w-md rounded-xl border border-reim-border bg-reim-surface p-6">
            <h3 className="text-base font-bold text-reim-text">Visualizador WebGL</h3>
            <p className="mt-2 text-sm text-reim-muted">
              El mapa interactivo requiere soporte de WebGL en el navegador para aceleración gráfica por hardware.
            </p>
          </div>
        </div>
      ) : (
        <div ref={containerRef} className="h-full w-full" />
      )}
      {children}
    </div>
  );
}
