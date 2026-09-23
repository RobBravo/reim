import { copyFile, mkdir } from "node:fs/promises";

const packageDist = new URL("../node_modules/maplibre-gl/dist/", import.meta.url);
const publicDir = new URL("../public/", import.meta.url);

await mkdir(publicDir, { recursive: true });

for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  await copyFile(new URL(file, packageDist), new URL(file, publicDir));
}
