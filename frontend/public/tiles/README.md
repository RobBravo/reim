# Central America PMTiles Basemap Asset

This directory contains the self-hosted PMTiles vector basemap asset used by REIM's `/map` view.

- **File:** `central-america.pmtiles`
- **Size:** ~3.2 MB
- **Source:** Protomaps daily planet build (`20260921.pmtiles`), derived from OpenStreetMap contributors (ODbL) and Natural Earth (Public Domain).
- **Bounding Box:** `-93.5, 6.5, -76.5, 18.5` (Centred on Central America: Belize, Guatemala, El Salvador, Honduras, Nicaragua, Costa Rica, Panama)
- **Zoom range:** 0 to 8
- **Extracted with:**
  ```bash
  pmtiles extract https://build.protomaps.com/20260921.pmtiles central-america.pmtiles --bbox=-93.5,6.5,-76.5,18.5 --maxzoom=8
  ```
- **License / Attribution:**
  Basemap data © OpenStreetMap contributors, Protomaps, and Natural Earth.
