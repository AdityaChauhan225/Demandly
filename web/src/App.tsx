import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Header } from './components/Header';
import { MapComponent } from './components/MapComponent';
import { Sidebar } from './components/Sidebar';
import {
  CellData,
  ZoneRank,
  ZoneHourlyApiResponse,
  MetaApiResponse,
  ViewState
} from './types';

// Default center: Bangalore tech hotspot corridor
const INITIAL_VIEW_STATE: ViewState = {
  longitude: 77.63,
  latitude: 12.95,
  zoom: 12.2,
  pitch: 0,
  bearing: 0
};

function getTimeRangeForPreset(preset: string) {
  const base = new Date('2026-09-01T00:00:00.000Z');
  let hours = 7 * 24;
  if (preset === '24h') hours = 24;
  else if (preset === '14d') hours = 14 * 24;
  const end = new Date(base.getTime() + hours * 3600 * 1000);
  return { from: base.toISOString(), to: end.toISOString() };
}

export const App: React.FC = () => {
  // Navigation & View
  const [viewState, setViewState] = useState<ViewState>(INITIAL_VIEW_STATE);
  const [activeResolution, setActiveResolution] = useState<number>(8);
  const [sidebarTab, setSidebarTab] = useState<'ranking' | 'detail' | 'architecture'>('ranking');

  // Filters & Controls
  const [categories, setCategories] = useState<string[]>(['food', 'cab', 'grocery', 'pharmacy']);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [timePreset, setTimePreset] = useState<string>('7d');
  const [privacyMode, setPrivacyMode] = useState<boolean>(true);

  // Time boundaries (computed from preset)
  const [timeRange, setTimeRange] = useState<{ from: string; to: string }>(() => getTimeRangeForPreset('7d'));

  // Data State
  const [cells, setCells] = useState<CellData[]>([]);
  const [topZones, setTopZones] = useState<ZoneRank[]>([]);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);
  const [zoneHourly, setZoneHourly] = useState<ZoneHourlyApiResponse | null>(null);

  // Telemetry & Loading State
  const [loadingCells, setLoadingCells] = useState<boolean>(false);
  const [loadingTopZones, setLoadingTopZones] = useState<boolean>(true);
  const [loadingHourly, setLoadingHourly] = useState<boolean>(false);
  const [cacheStatus, setCacheStatus] = useState<string | null>(null);
  const [queryTimeMs, setQueryTimeMs] = useState<string | null>(null);

  // AbortController for in-flight requests
  const abortControllerRef = useRef<AbortController | null>(null);

  // Update time preset
  const handleSelectTimePreset = useCallback((preset: string) => {
    setTimePreset(preset);
    setTimeRange(getTimeRangeForPreset(preset));
  }, []);

  // Fetch Metadata on mount
  useEffect(() => {
    fetch('/api/v1/meta')
      .then((res) => (res.ok ? res.json() : null))
      .then((data: MetaApiResponse | null) => {
        if (data && data.categories && data.categories.length > 0) {
          setCategories(data.categories);
        }
      })
      .catch((err) => console.warn('Meta fetch warning:', err));
  }, []);

  // Fetch Cells for current bbox
  const fetchCells = useCallback(
    (w: number, s: number, e: number, n: number, zoom: number) => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      setLoadingCells(true);
      const bboxStr = `${w.toFixed(4)},${s.toFixed(4)},${e.toFixed(4)},${n.toFixed(4)}`;

      const params = new URLSearchParams({
        bbox: bboxStr,
        zoom: zoom.toString(),
        from: timeRange.from,
        to: timeRange.to
      });
      if (selectedCategory) {
        params.append('category', selectedCategory);
      }

      fetch(`/api/v1/cells?${params.toString()}`, { signal: controller.signal })
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          setCacheStatus(res.headers.get('X-Cache') || 'MISS');
          setQueryTimeMs(res.headers.get('X-Query-Time-Ms') || '0');
          return res.json();
        })
        .then((data) => {
          setCells(data.cells || []);
          setActiveResolution(data.res || 8);
          setLoadingCells(false);
        })
        .catch((err) => {
          if (err.name !== 'AbortError') {
            console.error('Error fetching cells:', err);
            setLoadingCells(false);
          }
        });
    },
    [timeRange, selectedCategory]
  );

  // Fetch Top Zones
  useEffect(() => {
    setLoadingTopZones(true);
    const params = new URLSearchParams({
      from: timeRange.from,
      to: timeRange.to,
      res: '8',
      limit: '15'
    });
    if (selectedCategory) {
      params.append('category', selectedCategory);
    }

    fetch(`/api/v1/top-zones?${params.toString()}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && data.zones) {
          setTopZones(data.zones);
        } else {
          setTopZones([]);
        }
        setLoadingTopZones(false);
      })
      .catch((err) => {
        console.error('Error fetching top zones:', err);
        setLoadingTopZones(false);
      });
  }, [timeRange, selectedCategory]);

  // Fetch Zone Hourly Profile on zone selection
  const handleSelectZone = useCallback(
    (h3Cell: string, center: [number, number]) => {
      setSelectedZone(h3Cell);
      setLoadingHourly(true);

      // Smooth fly to center
      setViewState((vs) => ({
        ...vs,
        latitude: center[0],
        longitude: center[1],
        zoom: Math.max(vs.zoom, 13.0)
      }));

      const params = new URLSearchParams({
        from: timeRange.from,
        to: timeRange.to
      });
      if (selectedCategory) {
        params.append('category', selectedCategory);
      }

      fetch(`/api/v1/zones/${h3Cell}/hourly?${params.toString()}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          setZoneHourly(data);
          setLoadingHourly(false);
        })
        .catch((err) => {
          console.error('Error fetching hourly profile:', err);
          setLoadingHourly(false);
        });
    },
    [timeRange, selectedCategory]
  );

  const resetToHotspots = useCallback(() => {
    setSelectedZone(null);
    setZoneHourly(null);
    setViewState(INITIAL_VIEW_STATE);
  }, []);

  const totalDemand = cells.reduce((sum, c) => sum + c.count, 0);

  return (
    <div className="app-frame">
      {/* Top Navbar */}
      <Header
        timePreset={timePreset}
        onSelectTimePreset={handleSelectTimePreset}
        privacyMode={privacyMode}
        onTogglePrivacyMode={() => setPrivacyMode(!privacyMode)}
        cacheStatus={cacheStatus}
        queryTimeMs={queryTimeMs}
        activeResolution={activeResolution}
        onResetView={resetToHotspots}
        activeTab={sidebarTab}
        onSelectTab={setSidebarTab}
      />

      {/* Hero Overview Row - Matching Template Headline & Pill Badges */}
      <div className="hero-overview">
        <div className="hero-text">
          <span className="hero-title">Bangalore Demand Corridor</span>
          <span className="hero-subtitle">• High-throughput H3 spatial indexing</span>
        </div>

        <div className="kpi-pills-row">
          <div className="kpi-pill">
            <span className="kpi-pill-badge" />
            <span>P95 Latency:</span>
            <strong>&lt; 1 ms</strong>
          </div>
          <div className="kpi-pill">
            <span className="kpi-pill-badge" style={{ background: '#10b981' }} />
            <span>K-Suppression:</span>
            <strong>K ≥ 5</strong>
          </div>
          <div className="kpi-pill">
            <span className="kpi-pill-badge" style={{ background: '#0ea5e9' }} />
            <span>Indexed Events:</span>
            <strong>114,000+</strong>
          </div>
          <div className="kpi-pill">
            <span className="kpi-pill-badge" style={{ background: '#6366f1' }} />
            <span>Resolution:</span>
            <strong>Res {activeResolution}</strong>
          </div>
        </div>
      </div>

      {/* Main Split Content Area */}
      <div className="main-layout">
        <MapComponent
          viewState={viewState}
          onViewStateChange={setViewState}
          onBboxChange={fetchCells}
          cells={cells}
          selectedZone={selectedZone}
          onSelectZone={handleSelectZone}
          activeResolution={activeResolution}
          privacyMode={privacyMode}
          loading={loadingCells}
          onResetView={resetToHotspots}
          categories={categories}
          selectedCategory={selectedCategory}
          onSelectCategory={setSelectedCategory}
          cacheStatus={cacheStatus}
          queryTimeMs={queryTimeMs}
        />

        <Sidebar
          zones={topZones}
          selectedZone={selectedZone}
          onSelectZone={handleSelectZone}
          zoneHourlyData={zoneHourly}
          loadingHourly={loadingHourly}
          totalEventsInView={totalDemand}
          loadingTopZones={loadingTopZones}
          onResetView={resetToHotspots}
          activeTab={sidebarTab}
          onSelectTab={setSidebarTab}
        />
      </div>
    </div>
  );
};
