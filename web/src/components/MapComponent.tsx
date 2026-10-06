import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import DeckGL from '@deck.gl/react';
import { PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';
import maplibregl from 'maplibre-gl';
import { cellToBoundary, cellToLatLng } from 'h3-js';
import { Crosshair, AlertCircle, ArrowUpRight, Zap, Activity } from 'lucide-react';
import { CellData, ViewState } from '../types';

interface MapComponentProps {
  viewState: ViewState;
  onViewStateChange: (vs: ViewState) => void;
  onBboxChange: (w: number, s: number, e: number, n: number, zoom: number) => void;
  cells: CellData[];
  selectedZone: string | null;
  onSelectZone: (h3: string, center: [number, number]) => void;
  activeResolution: number;
  privacyMode: boolean;
  loading: boolean;
  onResetView?: () => void;
  categories: string[];
  selectedCategory: string;
  onSelectCategory: (cat: string) => void;
  cacheStatus: string | null;
  queryTimeMs: string | null;
}

// Minimalist Light Carto Positron basemap matching the sage & mint design aesthetic
const LIGHT_MAP_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

// Polished color interpolation for light cartography
function getColorForCount(count: number): [number, number, number, number] {
  if (count <= 10) return [74, 175, 140, 180];    // Soft Sage Teal
  if (count <= 35) return [34, 197, 94, 190];     // Vibrant Mint Emerald
  if (count <= 100) return [14, 165, 233, 200];   // Electric Cyan
  if (count <= 300) return [99, 102, 241, 215];   // Rich Indigo
  if (count <= 800) return [245, 158, 11, 225];   // Vivid Amber
  return [225, 29, 72, 235];                      // Deep Rose / Crimson
}

export const MapComponent: React.FC<MapComponentProps> = ({
  viewState,
  onViewStateChange,
  onBboxChange,
  cells,
  selectedZone,
  onSelectZone,
  activeResolution,
  privacyMode,
  loading,
  onResetView,
  categories,
  selectedCategory,
  onSelectCategory,
  cacheStatus,
  queryTimeMs
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [hoverInfo, setHoverInfo] = useState<{
    x: number;
    y: number;
    object?: CellData;
  } | null>(null);

  // Initialize MapLibre with Positron light style
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: LIGHT_MAP_STYLE,
      center: [viewState.longitude, viewState.latitude],
      zoom: viewState.zoom,
      pitch: viewState.pitch,
      bearing: viewState.bearing,
      interactive: false, // Handled by DeckGL
      attributionControl: false
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Debounce bbox reporting on map idle
  const debounceTimerRef = useRef<any>(null);

  const reportBbox = useCallback((vs: ViewState) => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }
    debounceTimerRef.current = setTimeout(() => {
      // Calculate approximate bounding box from center and zoom
      const zoom = vs.zoom;
      const spanLng = (360 / Math.pow(2, zoom)) * 1.5;
      const spanLat = (180 / Math.pow(2, zoom)) * 1.0;

      const w = Math.max(-180, vs.longitude - spanLng);
      const e = Math.min(180, vs.longitude + spanLng);
      const s = Math.max(-90, vs.latitude - spanLat);
      const n = Math.min(90, vs.latitude + spanLat);

      onBboxChange(w, s, e, n, zoom);
    }, 200);
  }, [onBboxChange]);

  // Sync MapLibre with DeckGL viewState and trigger debounced bbox query
  useEffect(() => {
    if (mapRef.current) {
      mapRef.current.jumpTo({
        center: [viewState.longitude, viewState.latitude],
        zoom: viewState.zoom,
        pitch: viewState.pitch,
        bearing: viewState.bearing
      });
    }
    reportBbox(viewState);
  }, [viewState, reportBbox]);

  const handleDeckViewStateChange = useCallback(({ viewState: newVs }: any) => {
    onViewStateChange(newVs);
  }, [onViewStateChange]);

  // Transform cells into polygons with boundaries
  const polygonData = useMemo(() => {
    return cells.map((c) => {
      try {
        const boundary = cellToBoundary(c.h3, true);
        return {
          h3: c.h3,
          count: c.count,
          polygon: boundary
        };
      } catch (e) {
        return null;
      }
    }).filter(Boolean);
  }, [cells]);

  // Raw points simulated comparison for Demo Mode
  const rawDemoPoints = useMemo(() => {
    if (privacyMode) return [];
    const points: Array<{ coordinates: [number, number]; category: string }> = [];
    cells.forEach((c) => {
      try {
        const [lat, lng] = cellToLatLng(c.h3);
        const sampleCount = Math.min(c.count, 25);
        for (let i = 0; i < sampleCount; i++) {
          const offsetLat = (Math.random() - 0.5) * 0.005;
          const offsetLng = (Math.random() - 0.5) * 0.005;
          points.push({
            coordinates: [lng + offsetLng, lat + offsetLat],
            category: 'demo_event'
          });
        }
      } catch (e) {
        // skip
      }
    });
    return points;
  }, [cells, privacyMode]);

  // DeckGL Layers
  const layers = useMemo(() => {
    if (!privacyMode) {
      // Comparison Raw Point Mode
      return [
        new ScatterplotLayer({
          id: 'raw-points-layer',
          data: rawDemoPoints,
          getPosition: (d: any) => d.coordinates,
          getRadius: 22,
          getFillColor: [225, 29, 72, 210],
          pickable: true
        })
      ];
    }

    return [
      new PolygonLayer({
        id: 'h3-hexagons-layer',
        data: polygonData,
        pickable: true,
        stroked: true,
        filled: true,
        extruded: false,
        wireframe: false,
        lineWidthMinPixels: 1,
        getPolygon: (d: any) => d.polygon,
        getFillColor: (d: any) => getColorForCount(d.count),
        getLineColor: (d: any) =>
          d.h3 === selectedZone
            ? [29, 60, 45, 255]     // Solid forest green outline when selected
            : [255, 255, 255, 200], // Crisp light outline
        getLineWidth: (d: any) => (d.h3 === selectedZone ? 3 : 1),
        updateTriggers: {
          getLineColor: [selectedZone],
          getLineWidth: [selectedZone]
        },
        onHover: (info: any) => {
          setHoverInfo(info.object ? { x: info.x, y: info.y, object: info.object } : null);
        },
        onClick: (info: any) => {
          if (info.object) {
            try {
              const [lat, lng] = cellToLatLng(info.object.h3);
              onSelectZone(info.object.h3, [lat, lng]);
            } catch (e) {
              onSelectZone(info.object.h3, [viewState.latitude, viewState.longitude]);
            }
          }
        }
      })
    ];
  }, [polygonData, rawDemoPoints, privacyMode, selectedZone, onSelectZone, viewState]);

  return (
    <div className="map-card-wrapper">
      {/* Map Card Header with Category Switcher and Telemetry */}
      <div className="map-card-header">
        {/* Category Filter Pills */}
        <div className="category-pills-bar">
          <button
            className={`cat-pill ${selectedCategory === '' ? 'active' : ''}`}
            onClick={() => onSelectCategory('')}
          >
            All Sectors
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              className={`cat-pill ${selectedCategory === cat ? 'active' : ''}`}
              onClick={() => onSelectCategory(cat)}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Telemetry Chips */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div className={`telemetry-chip ${cacheStatus === 'HIT' ? 'chip-hit' : 'chip-miss'}`}>
            <Zap size={12} />
            <span>{cacheStatus ? `CACHE ${cacheStatus}` : 'CACHE READY'}</span>
          </div>

          {queryTimeMs && (
            <div className="telemetry-chip">
              <Activity size={12} color="#0d9488" />
              <span>{queryTimeMs} ms</span>
            </div>
          )}

          <div className="telemetry-chip">
            <span style={{ color: '#1d3c2d', fontWeight: 700 }}>Res {activeResolution}</span>
          </div>
        </div>
      </div>

      {/* Map Viewport */}
      <div className="map-viewport">
        {/* MapLibre Basemap Container */}
        <div
          ref={mapContainerRef}
          style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}
        />

        {/* DeckGL Overlay */}
        <DeckGL
          viewState={viewState}
          onViewStateChange={handleDeckViewStateChange}
          controller={true}
          layers={layers}
        />

        {/* HUD Info Badges Top Left */}
        <div className="map-hud-top-left">
          <div className="hud-pill">
            <span>Zoom:</span>
            <strong>{viewState.zoom.toFixed(1)}</strong>
            <span>•</span>
            <span>H3 Res:</span>
            <strong>{activeResolution}</strong>
            <span>•</span>
            <span>Cells:</span>
            <strong>{cells.length.toLocaleString()}</strong>
          </div>

          {loading && (
            <div className="hud-pill" style={{ color: '#0d9488' }}>
              <div className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />
              <span>Updating view...</span>
            </div>
          )}

          {onResetView && (
            <button
              className="hud-btn"
              onClick={onResetView}
              title="Reset map view to Bangalore demand hotspot"
            >
              <Crosshair size={12} />
              <span>Reset Hotspots</span>
            </button>
          )}
        </div>

        {/* Empty Viewport Overlay */}
        {cells.length === 0 && !loading && onResetView && (
          <div className="map-empty-overlay">
            <AlertCircle size={22} color="#d97706" />
            <div>
              <div style={{ fontWeight: 700, fontSize: '13px', color: '#13241b' }}>
                No demand cells in current viewport
              </div>
              <div style={{ fontSize: '12px', color: '#6f8c7d' }}>
                Events are clustered in the Bangalore technology corridor.
              </div>
            </div>
            <button className="reset-view-pill-btn" onClick={onResetView}>
              <Crosshair size={13} />
              <span>Center on Bangalore</span>
            </button>
          </div>
        )}

        {/* Floating Demand Density Legend */}
        <div className="map-legend-card">
          <div className="legend-title">
            <span>Demand Density</span>
            <span style={{ color: '#15803d', fontWeight: 700 }}>K ≥ 5 (Suppressed)</span>
          </div>
          <div className="legend-gradient" />
          <div className="legend-labels">
            <span>&lt;10</span>
            <span>35</span>
            <span>100</span>
            <span>300</span>
            <span>800+</span>
          </div>
        </div>

        {/* Floating Corner Action Button (Directly from Template Mockup) */}
        {onResetView && (
          <button
            className="map-corner-action-btn"
            onClick={onResetView}
            title="Focus & Zoom to Primary Cluster"
            aria-label="Focus Primary Cluster"
          >
            <ArrowUpRight size={20} strokeWidth={2.5} />
          </button>
        )}

        {/* Hover Tooltip */}
        {hoverInfo && hoverInfo.object && (
          <div
            className="deck-tooltip"
            style={{ left: hoverInfo.x + 12, top: hoverInfo.y - 12 }}
          >
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#1d3c2d', fontWeight: 700, marginBottom: '2px' }}>
              {hoverInfo.object.h3}
            </div>
            <div style={{ fontSize: '15px', fontWeight: 800, color: '#13241b' }}>
              {hoverInfo.object.count.toLocaleString()}{' '}
              <span style={{ fontSize: '11px', fontWeight: 500, color: '#6f8c7d' }}>events</span>
            </div>
            <div style={{ fontSize: '10px', color: '#15803d', marginTop: '3px', fontWeight: 600 }}>
              🛡️ Privacy: Laplace Noised + K-Suppressed
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
