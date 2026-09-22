import type { StyleSpecification } from "maplibre-gl";

export function getDarkBasemapStyle(pmtilesUrl: string): StyleSpecification {
  return {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
      protomaps: {
        type: "vector",
        url: `pmtiles://${pmtilesUrl}`,
        attribution: "© OpenStreetMap contributors, Protomaps, Natural Earth",
      },
    },
    layers: [
      {
        id: "background",
        type: "background",
        paint: {
          "background-color": "#0a0f16",
        },
      },
      {
        id: "earth",
        type: "fill",
        source: "protomaps",
        "source-layer": "earth",
        paint: {
          "fill-color": "#111b27",
        },
      },
      {
        id: "water",
        type: "fill",
        source: "protomaps",
        "source-layer": "water",
        paint: {
          "fill-color": "#0a0f16",
        },
      },
      {
        id: "roads",
        type: "line",
        source: "protomaps",
        "source-layer": "roads",
        paint: {
          "line-color": "#162334",
          "line-width": 0.8,
        },
      },
      {
        id: "boundaries",
        type: "line",
        source: "protomaps",
        "source-layer": "boundaries",
        paint: {
          "line-color": "#1e2d42",
          "line-width": 1,
        },
      },
      {
        id: "places-country",
        type: "symbol",
        source: "protomaps",
        "source-layer": "places",
        filter: ["==", ["get", "kind"], "country"],
        layout: {
          "text-field": ["coalesce", ["get", "name:es"], ["get", "name"]],
          "text-size": 11,
          "text-font": ["Open Sans Regular"],
          "text-transform": "uppercase",
          "text-letter-spacing": 0.1,
        },
        paint: {
          "text-color": "#475569",
          "text-halo-color": "#0a0f16",
          "text-halo-width": 1,
        },
      },
    ],
  };
}
