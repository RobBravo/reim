# Modern Web Frontend: Scaffold & Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the modern web frontend scaffold under `frontend/` and deliver the interactive `/map` view — a WebGL choropleth of Central American countries and Panama's provinces over a self-hosted PMTiles basemap, with floating control panels, institutional dark aesthetic, and full provenance attribution.

**Architecture:** Next.js static export (`output: 'export'`), React, TypeScript, Tailwind CSS, TanStack Query, and MapLibre GL with Protomaps PMTiles protocol. In production, Caddy serves the static output directory directly, with `/api/*` routed to FastAPI on the same origin (no CORS or SSR required). The basemap is a self-hosted vector PMTiles extract of Central America stored in `frontend/public/tiles/`, read by MapLibre without third-party runtime dependencies. Boundaries are fetched from `GET /api/v1/geo/boundaries` and joined to observations in client-side state.

**Tech Stack:** Next.js 14/15 (App Router, static export), React 18/19, TypeScript, Tailwind CSS, `@tanstack/react-query`, `maplibre-gl`, `pmtiles`, `vitest`, `@testing-library/react`.

**Spec:** `docs/superpowers/specs/2026-09-21-modern-web-frontend-design.md`, §1-§6. This plan delivers the frontend project foundation and the `/map` page. `/series`, `/catalog`, `/runs`, and `apps/web` retirement follow in downstream increments.

---

## Global Constraints

- Backend remains untouched: FastAPI JSON contracts, rate limits, and database models are already complete and tested.
- Frontend directory: `frontend/` at repository root.
- The frontend gate from `frontend/`:
  `npm run typecheck && npm run lint && npm run test && npm run build`
- The backend gate from repository root:
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q`
- Palette tokens (spec §6):
  - Backgrounds: Canvas `#0f1720` (deep navy-black), Surface `#132234` (card/panel navy)
  - Accent / Active: `#e8b84b` (gold/amber)
  - Text: `#f1f5f9` (primary), `#94a3b8` (muted/secondary)
  - Borders: `#1e293b`
- Map basemap (spec §4, D3): Self-hosted PMTiles asset `frontend/public/tiles/central-america.pmtiles` — zero third-party tile service requests at runtime.
- Attribution (spec §4, README): The map view MUST render the ODbL attribution notice:
  `"Contains data from geoBoundaries.org and OpenStreetMap contributors, ODbL 1.0."`

---

### Task 1: Initialize Next.js project scaffold & tooling in `frontend/`

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next.config.mjs`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/.gitignore`
- Create: `frontend/src/test/setup.ts`
- Test: `frontend/src/test/smoke.test.ts`

**Interfaces:**
- Scripts: `npm run dev`, `npm run build`, `npm run lint`, `npm run typecheck`, `npm run test`.
- Static export build directory: `frontend/out/`.

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "reim-frontend",
  "version": "0.6.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint . --max-warnings 0",
    "typecheck": "tsc --noEmit",
    "test": "vitest run"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.66.0",
    "clsx": "^2.1.1",
    "lucide-react": "^0.475.0",
    "maplibre-gl": "^5.1.0",
    "next": "^15.1.7",
    "pmtiles": "^3.2.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "tailwind-merge": "^3.0.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.2.0",
    "@types/node": "^22.13.4",
    "@types/react": "^19.0.8",
    "@types/react-dom": "^19.0.3",
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "eslint": "^9.20.1",
    "eslint-config-next": "^15.1.7",
    "jsdom": "^26.0.0",
    "postcss": "^8.5.2",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.7.3",
    "vitest": "^3.0.5"
  }
}
```

- [ ] **Step 2: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [
      {
        "name": "next"
      }
    ],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Create `frontend/next.config.mjs`**

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
```

- [ ] **Step 4: Create `frontend/tailwind.config.ts` and `postcss.config.mjs`**

`frontend/tailwind.config.ts`:
```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        reim: {
          bg: "#0f1720",
          surface: "#132234",
          surfaceElevated: "#1a2c42",
          border: "#1e293b",
          borderSubtle: "#162232",
          gold: "#e8b84b",
          goldHover: "#f5c75d",
          goldMuted: "rgba(232, 184, 75, 0.15)",
          text: "#f1f5f9",
          muted: "#94a3b8",
          subtle: "#64748b",
        },
      },
    },
  },
  plugins: [],
};
export default config;
```

`frontend/postcss.config.mjs`:
```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 5: Create `frontend/vitest.config.ts` and `frontend/src/test/setup.ts`**

`frontend/vitest.config.ts`:
```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
```

`frontend/src/test/setup.ts`:
```typescript
import "@testing-library/jest-dom";
```

- [ ] **Step 6: Create `frontend/.gitignore`**

```gitignore
node_modules/
.next/
out/
build/
.DS_Store
*.log
```

- [ ] **Step 7: Install dependencies and write smoke test**

Run:
```bash
cd frontend && npm install
```

Create `frontend/src/test/smoke.test.ts`:
```typescript
import { describe, it, expect } from "vitest";

describe("Frontend toolchain smoke test", () => {
  it("verifies vitest and TypeScript environment work", () => {
    const greeting: string = "REIM Modern Web Frontend";
    expect(greeting).toContain("REIM");
  });
});
```

- [ ] **Step 8: Run checks to verify Task 1**

```bash
cd frontend && npm run typecheck && npm run test
```

Expected: `smoke.test.ts` passes with 0 errors.

---

### Task 2: Shared Shell, Navigation & Layout

**Files:**
- Create: `frontend/src/app/globals.css`
- Create: `frontend/src/app/layout.tsx`
- Create: `frontend/src/app/page.tsx`
- Create: `frontend/src/components/Header.tsx`
- Create: `frontend/src/components/Providers.tsx`
- Test: `frontend/src/components/__tests__/Header.test.tsx`

**Interfaces:**
- Reusable institutional header with links: `/` (Inicio), `/map` (Mapa), `/series` (Series), `/catalog` (Catálogo), `/runs` (Operaciones).
- `Providers.tsx` wrapping TanStack Query `QueryClientProvider`.

- [ ] **Step 1: Create `frontend/src/app/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --background: #0f1720;
  --foreground: #f1f5f9;
}

body {
  color: var(--foreground);
  background: var(--background);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
  overflow-x: hidden;
}
```

- [ ] **Step 2: Create `frontend/src/components/Providers.tsx`**

```typescript
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1000 * 60 * 5, // 5 minutes
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
```

- [ ] **Step 3: Create `frontend/src/components/Header.tsx`**

```typescript
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/", label: "Inicio" },
  { href: "/map/", label: "Mapa" },
  { href: "/series/", label: "Series" },
  { href: "/catalog/", label: "Catálogo" },
  { href: "/runs/", label: "Operaciones" },
];

export function Header() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 w-full border-b border-reim-border bg-reim-bg/90 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2 font-bold tracking-wider text-reim-text">
            <span className="flex h-7 w-7 items-center justify-center rounded bg-reim-gold/20 text-reim-gold font-mono text-xs border border-reim-gold/40">
              R
            </span>
            <span>REIM</span>
          </Link>
          <span className="hidden text-xs text-reim-subtle sm:inline-block border-l border-reim-border pl-3">
            Monitor Económico Regional
          </span>
        </div>

        <nav className="flex items-center gap-1 sm:gap-2">
          {NAV_LINKS.map((link) => {
            const isActive = pathname === link.href || (link.href !== "/" && pathname?.startsWith(link.href));
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-reim-surface text-reim-gold border border-reim-gold/30"
                    : "text-reim-muted hover:bg-reim-surface hover:text-reim-text"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
```

- [ ] **Step 4: Create `frontend/src/app/layout.tsx` and placeholder `page.tsx`**

`frontend/src/app/layout.tsx`:
```typescript
import type { Metadata } from "next";
import "./globals.css";
import { Header } from "@/components/Header";
import { Providers } from "@/components/Providers";

export const metadata: Metadata = {
  title: "REIM — Monitor Económico Regional de Centroamérica",
  description: "Estadísticas macroeconómicas oficiales y comparables para América Central.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" className="dark">
      <body className="min-h-screen bg-reim-bg text-reim-text antialiased">
        <Providers>
          <Header />
          <main>{children}</main>
        </Providers>
      </body>
    </html>
  );
}
```

`frontend/src/app/page.tsx`:
```typescript
import Link from "next/link";

export default function Home() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
      <div className="mb-10 text-center">
        <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl text-reim-text">
          Inteligencia Económica Regional
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-base text-reim-muted">
          Datos macroeconómicos oficiales para Nicaragua, Guatemala, El Salvador, Honduras, Costa Rica, Panamá y Belice.
        </p>
      </div>

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <Link
          href="/map/"
          className="group rounded-xl border border-reim-border bg-reim-surface p-6 transition-all hover:border-reim-gold/50"
        >
          <div className="text-xs font-semibold uppercase tracking-wider text-reim-gold">Explorador Espacial</div>
          <h2 className="mt-2 text-xl font-bold text-reim-text group-hover:text-reim-gold">Mapa Regional &rarr;</h2>
          <p className="mt-2 text-sm text-reim-muted">
            Visualización coroplética de indicadores nacionales y departamentales/provinciales.
          </p>
        </Link>
        <Link
          href="/series/"
          className="group rounded-xl border border-reim-border bg-reim-surface p-6 transition-all hover:border-reim-gold/50"
        >
          <div className="text-xs font-semibold uppercase tracking-wider text-reim-gold">Series de Tiempo</div>
          <h2 className="mt-2 text-xl font-bold text-reim-text group-hover:text-reim-gold">Gráficos Comparativos &rarr;</h2>
          <p className="mt-2 text-sm text-reim-muted">
            Evolución histórica y comparación multi-país con rigor de comparabilidad.
          </p>
        </Link>
        <Link
          href="/catalog/"
          className="group rounded-xl border border-reim-border bg-reim-surface p-6 transition-all hover:border-reim-gold/50"
        >
          <div className="text-xs font-semibold uppercase tracking-wider text-reim-gold">Metadatos & Licencias</div>
          <h2 className="mt-2 text-xl font-bold text-reim-text group-hover:text-reim-gold">Catálogo de Fuentes &rarr;</h2>
          <p className="mt-2 text-sm text-reim-muted">
            Transparencia total de fuentes oficiales, cadencias de actualización y licencias.
          </p>
        </Link>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Write Header unit test**

Create `frontend/src/components/__tests__/Header.test.tsx`:
```typescript
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Header } from "../Header";

vi.mock("next/navigation", () => ({
  usePathname: () => "/map/",
}));

describe("Header", () => {
  it("renders brand and navigation links", () => {
    render(<Header />);
    expect(screen.getByText("REIM")).toBeInTheDocument();
    expect(screen.getByText("Mapa")).toBeInTheDocument();
    expect(screen.getByText("Series")).toBeInTheDocument();
    expect(screen.getByText("Catálogo")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run checks to verify Task 2**

```bash
cd frontend && npm run test && npm run build
```

Expected: all tests pass, `next build` produces static export in `frontend/out/`.

---

### Task 3: API Client & Typed Query Hooks

**Files:**
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/hooks/useReimApi.ts`
- Test: `frontend/src/lib/__tests__/api.test.ts`

**Interfaces:**
- Typed access to REIM endpoints:
  - `GET /api/v1/countries` -> `Country[]`
  - `GET /api/v1/indicators` -> `Indicator[]`
  - `GET /api/v1/geo/boundaries?level=country|administrative_area` -> `GeoJSON.FeatureCollection`
  - `GET /api/v1/observations` -> `Observation[]`

- [ ] **Step 1: Create `frontend/src/types/api.ts`**

```typescript
export interface Country {
  id: string;
  name: string;
  iso2: string;
  iso3: string;
  currency_code: string;
  currency_name: string;
  is_active: boolean;
}

export interface AdministrativeArea {
  id: string;
  country_id: string;
  name: string;
  code: string;
  level: string;
}

export interface Indicator {
  id: string;
  code: string;
  name: string;
  description: string;
  frequency: string;
  unit: string;
  decimals: number;
  category: string;
  comparable: boolean;
  levels_comparable: boolean;
  currency_convertible: boolean;
  methodology_varies_by_country: boolean;
  requires_administrative_area: boolean;
}

export interface Observation {
  id: string;
  indicator_id: string;
  country_id: string;
  administrative_area_id?: string | null;
  period: string;
  value: number;
  currency_code?: string | null;
  unit?: string | null;
}

export interface BoundaryProperties {
  iso2?: string;
  iso3?: string;
  name?: string;
  code?: string;
  id?: string;
}

export interface GeoBoundariesCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id?: string | number;
    properties: BoundaryProperties;
    geometry: {
      type: "Polygon" | "MultiPolygon";
      coordinates: any;
    };
  }>;
}
```

- [ ] **Step 2: Create `frontend/src/lib/api.ts`**

```typescript
import {
  Country,
  Indicator,
  Observation,
  GeoBoundariesCollection,
} from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`);
  if (!res.ok) {
    throw new Error(`API Error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const reimApi = {
  getCountries: () => fetchJson<Country[]>("/api/v1/countries"),
  getIndicators: () => fetchJson<Indicator[]>("/api/v1/indicators"),
  getBoundaries: (level: "country" | "administrative_area") =>
    fetchJson<GeoBoundariesCollection>(`/api/v1/geo/boundaries?level=${level}`),
  getObservations: (params: {
    indicator_id: string;
    start_date?: string;
    end_date?: string;
  }) => {
    const query = new URLSearchParams({
      indicator_id: params.indicator_id,
      page_size: "1000",
    });
    if (params.start_date) query.set("start_date", params.start_date);
    if (params.end_date) query.set("end_date", params.end_date);
    return fetchJson<Observation[]>(`/api/v1/observations?${query.toString()}`);
  },
};
```

- [ ] **Step 3: Create `frontend/src/hooks/useReimApi.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { reimApi } from "@/lib/api";

export function useCountries() {
  return useQuery({
    queryKey: ["countries"],
    queryFn: reimApi.getCountries,
  });
}

export function useIndicators() {
  return useQuery({
    queryKey: ["indicators"],
    queryFn: reimApi.getIndicators,
  });
}

export function useBoundaries(level: "country" | "administrative_area") {
  return useQuery({
    queryKey: ["boundaries", level],
    queryFn: () => reimApi.getBoundaries(level),
    staleTime: Infinity, // Geometries never change during a session
  });
}

export function useObservations(indicatorId?: string) {
  return useQuery({
    queryKey: ["observations", indicatorId],
    queryFn: () =>
      indicatorId ? reimApi.getObservations({ indicator_id: indicatorId }) : Promise.resolve([]),
    enabled: Boolean(indicatorId),
  });
}
```

- [ ] **Step 4: Write unit tests for API Client**

Create `frontend/src/lib/__tests__/api.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { reimApi } from "../api";

describe("reimApi client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches countries successfully", async () => {
    const mockCountries = [{ id: "1", iso2: "NI", name: "Nicaragua" }];
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockCountries,
    });

    const data = await reimApi.getCountries();
    expect(fetch).toHaveBeenCalledWith("/api/v1/countries");
    expect(data).toEqual(mockCountries);
  });

  it("throws on HTTP error response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    await expect(reimApi.getCountries()).rejects.toThrow("API Error 500");
  });
});
```

- [ ] **Step 5: Run checks to verify Task 3**

```bash
cd frontend && npm run test
```

Expected: All unit tests pass cleanly.

---

### Task 4: Self-Hosted PMTiles Basemap Asset & MapLibre Setup

**Files:**
- Create: `frontend/public/tiles/` directory
- Procure / extract: `frontend/public/tiles/central-america.pmtiles`
- Create: `frontend/src/lib/map-style.ts`
- Create: `frontend/src/components/map/MapLibreWrapper.tsx`
- Test: `frontend/src/components/map/__tests__/MapLibreWrapper.test.tsx`

**Interfaces:**
- `central-america.pmtiles` asset checked into repository / built offline with range-request clipping.
- `MapLibreWrapper` handles map lifecycle, WebGL context, and PMTiles protocol registration.

- [ ] **Step 1: Procure the Central America PMTiles basemap extract**

Bounding box for Central America:
`min_lon: -93.5, min_lat: 6.5, max_lon: -76.5, max_lat: 18.5`.

Extract `central-america.pmtiles` using `go-pmtiles` from Protomaps daily planet build:
```bash
mkdir -p frontend/public/tiles
# Download go-pmtiles binary if not present, then extract
curl -sL https://github.com/protomaps/go-pmtiles/releases/download/v1.31.2/go-pmtiles_1.31.2_Linux_x86_64.tar.gz | tar -xz -C /tmp
/tmp/pmtiles extract https://build.protomaps.com/20260921.pmtiles frontend/public/tiles/central-america.pmtiles --bbox=-93.5,6.5,-76.5,18.5 --maxzoom=8
```

Verify the asset file exists and is under 20MB.

- [ ] **Step 2: Create `frontend/src/lib/map-style.ts`**

Define an institutional dark basemap style for MapLibre:
```typescript
import type { StyleSpecification } from "maplibre-gl";

export function getDarkBasemapStyle(pmtilesUrl: string): StyleSpecification {
  return {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
      protomaps: {
        type: "vector",
        url: `pmtiles://${pmtilesUrl}`,
        attribution: "© OpenStreetMap contributors, Protomaps",
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
        id: "places",
        type: "symbol",
        source: "protomaps",
        "source-layer": "places",
        filter: ["==", ["get", "pmap:kind"], "country"],
        layout: {
          "text-field": ["get", "name:es"],
          "text-size": 11,
          "text-font": ["Open Sans Regular"],
        },
        paint: {
          "text-color": "#64748b",
          "text-halo-color": "#0a0f16",
          "text-halo-width": 1,
        },
      },
    ],
  };
}
```

- [ ] **Step 3: Create `frontend/src/components/map/MapLibreWrapper.tsx`**

```typescript
"use client";

import { useEffect, useRef, useState, ReactNode } from "react";
import maplibregl, { Map as MapLibreMap } from "maplibre-gl";
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
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasWebGl, setHasWebGl] = useState(true);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    try {
      const protocol = new Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);

      const style = getDarkBasemapStyle("/tiles/central-america.pmtiles");

      const map = new maplibregl.Map({
        container: containerRef.current,
        style,
        center: [-85.5, 12.8],
        zoom: 5.2,
        minZoom: 4,
        maxZoom: 9,
        attributionControl: false,
      });

      map.addControl(
        new maplibregl.AttributionControl({
          compact: true,
          customAttribution: "Contains data from geoBoundaries.org and OpenStreetMap contributors, ODbL 1.0.",
        }),
        "bottom-right"
      );

      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

      map.on("load", () => {
        mapRef.current = map;
        setIsLoaded(true);
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

  if (!hasWebGl) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-reim-bg p-6 text-center text-reim-muted">
        <p>No se pudo inicializar WebGL en este navegador para renderizar el mapa interactivo.</p>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden">
      <div ref={containerRef} className="h-full w-full" />
      {isLoaded && children}
    </div>
  );
}
```

- [ ] **Step 4: Write MapLibreWrapper component test**

Create `frontend/src/components/map/__tests__/MapLibreWrapper.test.tsx`:
```typescript
import { render } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MapLibreWrapper } from "../MapLibreWrapper";

describe("MapLibreWrapper", () => {
  it("renders container element", () => {
    const { container } = render(<MapLibreWrapper />);
    expect(container.firstChild).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run checks to verify Task 4**

```bash
cd frontend && npm run test
```

Expected: Tests pass cleanly.

---

### Task 5: Interactive Choropleth Map Page (`/map`)

**Files:**
- Create: `frontend/src/lib/choropleth.ts`
- Create: `frontend/src/components/map/MapControls.tsx`
- Create: `frontend/src/components/map/MapDetailCard.tsx`
- Create: `frontend/src/app/map/page.tsx`
- Test: `frontend/src/lib/__tests__/choropleth.test.ts`
- Test: `frontend/src/components/map/__tests__/MapControls.test.tsx`

**Interfaces:**
- Color scale mapping numerical values to gold ramp (`#16283b` -> `#4d3c19` -> `#9c7827` -> `#e8b84b`).
- Floating control overlay on `/map`: Indicator select, Level toggle (National vs Provincial), Period selector.
- Click/hover popup/card showing territory name, value, and metadata.
- Attribution footer adhering to ODbL requirements.

- [ ] **Step 1: Create `frontend/src/lib/choropleth.ts`**

```typescript
export interface ColorRampStop {
  color: string;
  threshold: number;
}

export function computeChoroplethScale(values: number[]): {
  getColor: (val: number | null | undefined) => string;
  min: number;
  max: number;
} {
  const valid = values.filter((v): v is number => typeof v === "number" && !isNaN(v));
  if (valid.length === 0) {
    return {
      getColor: () => "#1e293b",
      min: 0,
      max: 0,
    };
  }

  const min = Math.min(...valid);
  const max = Math.max(...valid);

  // 4-stop gold ramp on dark surface
  const ramp = ["#1e293b", "#5a451d", "#9b752b", "#e8b84b"];

  const getColor = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "#1a2533";
    if (min === max) return ramp[3];
    const fraction = (val - min) / (max - min);
    if (fraction < 0.25) return ramp[0];
    if (fraction < 0.5) return ramp[1];
    if (fraction < 0.75) return ramp[2];
    return ramp[3];
  };

  return { getColor, min, max };
}
```

- [ ] **Step 2: Create `frontend/src/components/map/MapControls.tsx`**

```typescript
"use client";

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
  return (
    <div className="absolute left-4 top-4 z-10 w-80 rounded-xl border border-reim-border bg-reim-surface/95 p-4 shadow-xl backdrop-blur-md">
      <div className="mb-3">
        <label className="text-xs font-semibold uppercase tracking-wider text-reim-gold">Indicador</label>
        <select
          value={selectedIndicatorId}
          onChange={(e) => onSelectIndicator(e.target.value)}
          className="mt-1 w-full rounded-md border border-reim-border bg-reim-bg px-3 py-2 text-sm text-reim-text focus:border-reim-gold focus:outline-none"
        >
          {indicators.map((ind) => (
            <option key={ind.id} value={ind.id}>
              {ind.name}
            </option>
          ))}
        </select>
      </div>

      <div className="mb-3">
        <label className="text-xs font-semibold uppercase tracking-wider text-reim-gold">Nivel Geográfico</label>
        <div className="mt-1 flex rounded-md bg-reim-bg p-1 border border-reim-border">
          <button
            onClick={() => onSelectLevel("country")}
            className={`flex-1 rounded py-1 text-xs font-medium transition-colors ${
              level === "country" ? "bg-reim-surface text-reim-gold shadow" : "text-reim-muted hover:text-reim-text"
            }`}
          >
            Nacional
          </button>
          <button
            onClick={() => onSelectLevel("administrative_area")}
            className={`flex-1 rounded py-1 text-xs font-medium transition-colors ${
              level === "administrative_area" ? "bg-reim-surface text-reim-gold shadow" : "text-reim-muted hover:text-reim-text"
            }`}
          >
            Provincial (PA)
          </button>
        </div>
      </div>

      {periods.length > 0 && (
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider text-reim-gold">
            Período: <span className="text-reim-text font-mono">{selectedPeriod}</span>
          </label>
          <select
            value={selectedPeriod}
            onChange={(e) => onSelectPeriod(e.target.value)}
            className="mt-1 w-full rounded-md border border-reim-border bg-reim-bg px-3 py-1.5 text-xs text-reim-text focus:border-reim-gold focus:outline-none"
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
  );
}
```

- [ ] **Step 3: Create `frontend/src/components/map/MapDetailCard.tsx`**

```typescript
"use client";

import { Indicator } from "@/types/api";

interface MapDetailCardProps {
  name: string;
  value?: number | null;
  unit?: string | null;
  period?: string;
  indicator?: Indicator;
  onClose: () => void;
}

export function MapDetailCard({
  name,
  value,
  unit,
  period,
  indicator,
  onClose,
}: MapDetailCardProps) {
  return (
    <div className="absolute right-4 top-4 z-10 w-72 rounded-xl border border-reim-border bg-reim-surface/95 p-4 shadow-xl backdrop-blur-md">
      <div className="flex items-start justify-between">
        <div>
          <span className="text-xs font-medium text-reim-gold uppercase tracking-wider">Territorio</span>
          <h3 className="text-base font-bold text-reim-text">{name}</h3>
        </div>
        <button
          onClick={onClose}
          className="text-reim-subtle hover:text-reim-text p-1 text-sm font-bold"
        >
          ✕
        </button>
      </div>

      <div className="mt-3 border-t border-reim-border pt-3">
        <div className="text-xs text-reim-muted">{indicator?.name || "Valor"}</div>
        <div className="mt-1 text-2xl font-extrabold text-reim-gold font-mono">
          {value !== null && value !== undefined ? value.toLocaleString() : "Sin datos"}
          {unit && <span className="ml-1 text-xs text-reim-muted font-normal">{unit}</span>}
        </div>
        {period && <div className="mt-1 text-xs text-reim-subtle">Período: {period}</div>}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create `frontend/src/app/map/page.tsx`**

```typescript
"use client";

import { useState, useMemo, useCallback } from "react";
import { Map as MapLibreMap } from "maplibre-gl";
import { MapLibreWrapper } from "@/components/map/MapLibreWrapper";
import { MapControls } from "@/components/map/MapControls";
import { MapDetailCard } from "@/components/map/MapDetailCard";
import { useIndicators, useBoundaries, useObservations, useCountries } from "@/hooks/useReimApi";
import { computeChoroplethScale } from "@/lib/choropleth";

export default function MapPage() {
  const [level, setLevel] = useState<"country" | "administrative_area">("country");
  const [selectedIndicatorId, setSelectedIndicatorId] = useState<string>("");
  const [selectedPeriod, setSelectedPeriod] = useState<string>("");
  const [selectedFeature, setSelectedFeature] = useState<{ name: string; id: string } | null>(null);
  const [mapInstance, setMapInstance] = useState<MapLibreMap | null>(null);

  const { data: indicators = [] } = useIndicators();
  const { data: countries = [] } = useCountries();
  const { data: boundaries } = useBoundaries(level);

  // Auto-select first indicator when loaded
  const currentIndicatorId = selectedIndicatorId || (indicators[0]?.id ?? "");
  const selectedIndicator = indicators.find((i) => i.id === currentIndicatorId);

  const { data: observations = [], isLoading: isObsLoading } = useObservations(currentIndicatorId);

  // Extract available periods
  const periods = useMemo(() => {
    const set = new Set<string>();
    observations.forEach((o) => {
      if (level === "country" && !o.administrative_area_id) set.add(o.period);
      if (level === "administrative_area" && o.administrative_area_id) set.add(o.period);
    });
    return Array.from(set).sort().reverse();
  }, [observations, level]);

  const activePeriod = selectedPeriod || periods[0] || "";

  // Filter observations for current period & level
  const observationsMap = useMemo(() => {
    const map = new Map<string, number>();
    observations.forEach((o) => {
      if (o.period === activePeriod) {
        if (level === "country" && !o.administrative_area_id) {
          map.set(o.country_id, o.value);
        } else if (level === "administrative_area" && o.administrative_area_id) {
          map.set(o.administrative_area_id, o.value);
        }
      }
    });
    return map;
  }, [observations, activePeriod, level]);

  // Update GeoJSON layer on map
  const onMapLoaded = useCallback((map: MapLibreMap) => {
    setMapInstance(map);
  }, []);

  // Sync GeoJSON features with choropleth colors
  useMemo(() => {
    if (!mapInstance || !boundaries) return;

    const sourceId = "reim-boundaries";
    const fillLayerId = "reim-boundaries-fill";
    const lineLayerId = "reim-boundaries-line";

    if (!mapInstance.getSource(sourceId)) {
      mapInstance.addSource(sourceId, {
        type: "geojson",
        data: boundaries as any,
      });

      mapInstance.addLayer({
        id: fillLayerId,
        type: "fill",
        source: sourceId,
        paint: {
          "fill-color": "#1a2533",
          "fill-opacity": 0.75,
        },
      });

      mapInstance.addLayer({
        id: lineLayerId,
        type: "line",
        source: sourceId,
        paint: {
          "line-color": "#e8b84b",
          "line-width": 1.2,
        },
      });

      mapInstance.on("click", fillLayerId, (e) => {
        const feature = e.features?.[0];
        if (feature?.properties) {
          setSelectedFeature({
            name: feature.properties.name || feature.properties.iso2 || "Territorio",
            id: feature.properties.id || feature.properties.iso2 || "",
          });
        }
      });
    } else {
      (mapInstance.getSource(sourceId) as any).setData(boundaries);
    }
  }, [mapInstance, boundaries, observationsMap]);

  return (
    <div className="relative h-[calc(100vh-3.5rem)] w-full overflow-hidden bg-reim-bg">
      <MapLibreWrapper onMapLoaded={onMapLoaded}>
        <MapControls
          indicators={indicators}
          selectedIndicatorId={currentIndicatorId}
          onSelectIndicator={(id) => {
            setSelectedIndicatorId(id);
            setSelectedPeriod("");
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

        {selectedFeature && (
          <MapDetailCard
            name={selectedFeature.name}
            value={observationsMap.get(selectedFeature.id)}
            unit={selectedIndicator?.unit}
            period={activePeriod}
            indicator={selectedIndicator}
            onClose={() => setSelectedFeature(null)}
          />
        )}
      </MapLibreWrapper>
    </div>
  );
}
```

- [ ] **Step 5: Write unit tests for choropleth scale**

Create `frontend/src/lib/__tests__/choropleth.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { computeChoroplethScale } from "../choropleth";

describe("computeChoroplethScale", () => {
  it("returns dark fallback for empty values", () => {
    const scale = computeChoroplethScale([]);
    expect(scale.getColor(10)).toBe("#1e293b");
  });

  it("scales values from min to max across color ramp", () => {
    const scale = computeChoroplethScale([10, 20, 30, 40]);
    expect(scale.getColor(10)).toBe("#1e293b");
    expect(scale.getColor(40)).toBe("#e8b84b");
  });
});
```

- [ ] **Step 6: Run checks to verify Task 5**

```bash
cd frontend && npm run test && npm run build
```

Expected: Static export builds successfully in `frontend/out/`, including `/map/index.html`.

---

### Task 6: Makefile Targets & Full Verification

**Files:**
- Modify: `Makefile`
- Test: Run root gate & frontend gate

- [ ] **Step 1: Add frontend targets to `Makefile`**

In `Makefile`, add:
```makefile
# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------
.PHONY: frontend-install
frontend-install: ## Install frontend npm dependencies
	cd frontend && npm install

.PHONY: frontend-dev
frontend-dev: ## Run the frontend in development mode
	cd frontend && npm run dev

.PHONY: frontend-build
frontend-build: ## Build the static export of the frontend
	cd frontend && npm run build

.PHONY: frontend-test
frontend-test: ## Run frontend test suite
	cd frontend && npm run test

.PHONY: frontend-check
frontend-check: ## Run frontend typecheck, lint, test and build
	cd frontend && npm run typecheck && npm run lint && npm run test && npm run build
```

- [ ] **Step 2: Run both quality gates end-to-end**

Run frontend verification:
```bash
make frontend-check
```

Run backend verification:
```bash
make check
```

Expected: Both gates exit with code 0.

---

## Deliberately not in this plan

- **`/series` chart implementation:** TradingView `lightweight-charts` and small-multiples logic will be implemented in its own focused plan.
- **`/catalog` and `/runs` full client rewrite:** Implemented in the downstream catalog/observability plan.
- **Retirement of `apps/web`:** Server-rendered templates will be removed once the frontend reaches complete parity.
- **Production Caddyfile reconfiguration:** Static `file_server` serving will be configured in the deployment integration plan.

---

## Done when

- `frontend/` is initialized with Next.js, React, Tailwind CSS, TanStack Query, and Vitest.
- Institutional dark palette tokens (`#0f1720`, `#132234`, `#e8b84b`) are configured and applied in layouts.
- Header navigation provides consistent access to all platform views.
- Central America PMTiles basemap is self-hosted and rendered via MapLibre GL.
- `/map` view loads country and provincial boundary GeoJSON from `GET /api/v1/geo/boundaries` and joins it with observations.
- Floating controls allow indicator, period, and geographic level selection.
- GeoBoundaries ODbL attribution notice is visibly displayed.
- All tests pass: `npm run test` and `npm run build` in `frontend/`, and `make check` on backend.
