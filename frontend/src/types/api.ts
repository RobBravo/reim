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
