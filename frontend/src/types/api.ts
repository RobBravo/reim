export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
  returned: number;
  has_more: boolean;
}

export interface PageResponse<T> {
  data: T[];
  meta: PageMeta;
}

export interface ComparisonIndicator {
  code: string;
  name: string;
  frequency: string;
}

export interface ComparisonSeries {
  country_iso2: string;
  country_iso3: string;
  country_name: string;
  units: string[];
  currency_codes: Array<string | null>;
  source_keys: string[];
  organization_codes: string[];
  observations: number;
  first_period: string | null;
  last_period: string | null;
}

export interface ComparisonRow {
  period_start: string;
  period_end: string;
  period_label: string;
  values: Record<string, number | null>;
  values_converted?: Record<string, number | null>;
  rates?: Record<string, number | null>;
  rate_basis?: Record<string, string | null>;
}

export interface ConversionBlock {
  target_currency: string;
  rate_indicator_code: string;
  rate_source_key: string | null;
  basis: string;
  converted: number;
  already_at_target: number;
  no_rate: number;
  caveats: string[];
}

export interface ComparisonResponse {
  meta: PageMeta;
  indicator: ComparisonIndicator;
  comparable: boolean;
  levels_comparable: boolean;
  comparability_notes: string[];
  conversion?: ConversionBlock;
  series: ComparisonSeries[];
  data: ComparisonRow[];
}

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
  country_iso2: string;
  country_iso3: string;
  country_name: string;
  indicator_code: string;
  indicator_name: string;
  period_label: string;
  value_numeric: number | null;
  unit: string;
  currency_code?: string | null;
  administrative_area_code?: string | null;
  administrative_area_name?: string | null;
}

export interface BoundaryProperties {
  iso2?: string;
  code?: string;
  name?: string;
  fillColor?: string;
  value?: number | null;
}

export interface GeoBoundariesCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id?: string | number;
    properties: BoundaryProperties;
    geometry: Polygon | MultiPolygon;
  }>;
}
import type { MultiPolygon, Polygon } from "geojson";
