export interface CellData {
  h3: string;
  count: number;
}

export interface CellsApiResponse {
  res: number;
  source: string;
  from: string;
  to: string;
  cells: CellData[];
  suppressed: boolean;
  k: number;
}

export interface ZoneRank {
  rank: number;
  h3: string;
  center: [number, number];
  count: number;
  previous: number;
  growth_pct: number;
}

export interface TopZonesApiResponse {
  window: { from: string; to: string };
  previous_window: { from: string; to: string };
  zones: ZoneRank[];
}

export interface HourCount {
  hour: number;
  count: number;
}

export interface ZoneHourlyApiResponse {
  h3: string;
  hours: HourCount[];
  peak_hours: number[];
}

export interface MetaApiResponse {
  categories: string[];
  time_range: {
    from: string | null;
    to: string | null;
  };
  k: number;
  epsilon: number;
  resolutions: {
    zoom_range: string;
    res: number;
    approx_edge: string;
  }[];
  total_cells: number;
  total_events: number;
}

export interface ViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
  [key: string]: any;
}
