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

export interface DataSource {
  id: string;
  source_key: string;
  name: string;
  description: string | null;
  category: string;
  access_type: string;
  base_url: string;
  frequency: string;
  format: string;
  connector_path: string | null;
  license: string | null;
  documentation_url: string | null;
  is_official: boolean;
  is_active: boolean;
  disabled_reason: string | null;
  organization_id: string;
  country_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Organization {
  id: string;
  code: string;
  name: string;
  short_name: string | null;
  organization_type: string;
  website_url: string | null;
  is_official: boolean;
  country_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PipelineSummary {
  pipeline_key: string;
  source_key: string;
  enabled: boolean;
  disabled_reason: string | null;
  frequency: string;
  indicators: string[];
  last_run_at: string | null;
  last_run_status: string | null;
  last_run_duration_ms: number | null;
  last_success_at: string | null;
  last_error_type: string | null;
  last_error_message: string | null;
  records_inserted_last_run: number | null;
  records_updated_last_run: number | null;
  records_rejected_last_run: number | null;
  observation_count: number;
  latest_period_end: string | null;
  data_age_days: number | null;
  is_stale: boolean | null;
}

export type PipelineRunStatus = "running" | "success" | "partial" | "failed" | "skipped";

export interface PipelineRun {
  id: string;
  pipeline_key: string;
  source_id: string | null;
  connector_version: string | null;
  pipeline_version: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  status: PipelineRunStatus;
  records_extracted: number;
  records_inserted: number;
  records_updated: number;
  records_unchanged: number;
  records_rejected: number;
  error_type: string | null;
  error_message: string | null;
  run_metadata: Record<string, unknown>;
  created_at: string;
}

export type QualityCheckStatus = "passed" | "failed" | "skipped";
export type QualityCheckSeverity = "info" | "warning" | "error" | "critical";

export interface QualityCheck {
  id: string;
  check_name: string;
  check_type: string;
  status: QualityCheckStatus;
  severity: QualityCheckSeverity;
  indicator_code: string | null;
  period_label: string | null;
  expected_value: string | null;
  actual_value: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface PipelineRunDetail extends PipelineRun {
  quality_checks: QualityCheck[];
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
