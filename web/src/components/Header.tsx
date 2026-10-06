import React from 'react';
import { Layers, ShieldCheck, ShieldAlert, Zap, Clock, Activity, Crosshair, ArrowUpRight } from 'lucide-react';

interface HeaderProps {
  timePreset: string;
  onSelectTimePreset: (preset: string) => void;
  privacyMode: boolean;
  onTogglePrivacyMode: () => void;
  cacheStatus: string | null;
  queryTimeMs: string | null;
  activeResolution: number;
  onResetView?: () => void;
  activeTab?: 'ranking' | 'detail' | 'architecture';
  onSelectTab?: (tab: 'ranking' | 'detail' | 'architecture') => void;
}

export const Header: React.FC<HeaderProps> = ({
  timePreset,
  onSelectTimePreset,
  privacyMode,
  onTogglePrivacyMode,
  cacheStatus,
  queryTimeMs,
  activeResolution,
  onResetView,
  activeTab = 'ranking',
  onSelectTab
}) => {
  return (
    <header className="app-header">
      {/* Brand - Styled as template logo */}
      <div className="brand-section">
        <div className="brand-logo" title="Demandly H3 Engine">
          <Layers size={20} strokeWidth={2.4} />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h1 className="brand-title">Demandly</h1>
            <span className="brand-badge">H3 Analytics</span>
          </div>
        </div>
      </div>

      {/* Nav Center Pills - Matching template navigation style */}
      <nav className="nav-links" aria-label="Main Navigation">
        <button
          className={`nav-link-btn ${activeTab === 'ranking' ? 'active' : ''}`}
          onClick={() => onSelectTab && onSelectTab('ranking')}
        >
          <span>Top Clusters</span>
        </button>
        <button
          className={`nav-link-btn ${activeTab === 'detail' ? 'active' : ''}`}
          onClick={() => onSelectTab && onSelectTab('detail')}
        >
          <span>Zone Profile</span>
        </button>
        <button
          className={`nav-link-btn ${activeTab === 'architecture' ? 'active' : ''}`}
          onClick={() => onSelectTab && onSelectTab('architecture')}
        >
          <span>Privacy & Specs</span>
        </button>
      </nav>

      {/* Controls & Quick Actions */}
      <div className="controls-bar">
        {/* Time Preset Dropdown Pill */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Clock size={14} color="#6f8c7d" />
          <select
            className="select-pill"
            value={timePreset}
            onChange={(e) => onSelectTimePreset(e.target.value)}
            title="Aggregation Time Window"
          >
            <option value="24h">Last 24 Hours</option>
            <option value="7d">Last 7 Days (Hourly)</option>
            <option value="14d">Full 14 Days</option>
          </select>
        </div>

        {/* Privacy Mode Toggle */}
        <button
          className={`privacy-toggle-btn ${!privacyMode ? 'raw-mode' : ''}`}
          onClick={onTogglePrivacyMode}
          title={privacyMode ? "Privacy active: H3 Hexagons + K-Suppression (K≥5)" : "Raw demo comparison mode"}
        >
          {privacyMode ? (
            <>
              <ShieldCheck size={14} />
              <span>Privacy Active (K≥5)</span>
            </>
          ) : (
            <>
              <ShieldAlert size={14} />
              <span>Raw Points Demo</span>
            </>
          )}
        </button>

        {/* Reset / Focus Bangalore Action Button */}
        {onResetView && (
          <button
            className="header-cta-btn"
            onClick={onResetView}
            title="Focus viewport on Bangalore demand hotspot"
          >
            <Crosshair size={13} />
            <span>Focus Bangalore</span>
          </button>
        )}
      </div>
    </header>
  );
};
