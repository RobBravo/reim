const OPEN_LICENCES = new Set(["CC-BY-4.0", "public_official_data"]);

export function isRedistributable(license: string | null): boolean {
  return license !== null && OPEN_LICENCES.has(license);
}
