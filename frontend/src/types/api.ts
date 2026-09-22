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
    geometry: {
      type: "Polygon" | "MultiPolygon";
      coordinates: any;
    };
  }>;
}
