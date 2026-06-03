import { useState, useEffect, useCallback, useRef } from 'react';
import Map, { Marker, NavigationControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { getPorts, getRiskScores } from '../api';
import { scoreToColor, scoreToLabel, tierToRadius } from '../utils/colors';
import RiskBadge from './RiskBadge';

const MAP_STYLE = {
  version: 8,
  sources: {
    carto: {
      type: 'raster',
      tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'],
      tileSize: 256,
      attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://openstreetmap.org/">OSM</a>',
    },
  },
  layers: [{ id: 'carto-layer', type: 'raster', source: 'carto' }],
};

const SHOCK_EVENTS = [
  { year: 2020, month: 4,  label: 'COVID peak' },
  { year: 2021, month: 3,  label: 'Suez blockage' },
  { year: 2021, month: 10, label: 'US congestion' },
  { year: 2023, month: 12, label: 'Red Sea crisis' },
];

const ALL_MONTHS = [];
for (let y = 2020; y <= 2024; y++)
  for (let m = 1; m <= 12; m++)
    ALL_MONTHS.push({ year: y, month: m, label: `${y}-${String(m).padStart(2,'0')}` });

export default function WorldRiskMap({ onPortSelect }) {
  const [ports,      setPorts]      = useState([]);
  const [riskMap,    setRiskMap]    = useState({});
  const [sliderIdx,  setSliderIdx]  = useState(ALL_MONTHS.length - 1);
  const [tooltip,    setTooltip]    = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState(null);
  const riskCache = useRef({});

  // Load port list once
  useEffect(() => {
    getPorts()
      .then(data => { setPorts(data); setLoading(false); })
      .catch(() => setError('Cannot reach API — is the backend running?'));
  }, []);

  // Load risk scores when slider changes
  useEffect(() => {
    const { year, month } = ALL_MONTHS[sliderIdx];
    const key = `${year}-${month}`;
    if (riskCache.current[key]) {
      setRiskMap(riskCache.current[key]);
      return;
    }
    getRiskScores(year, month)
      .then(data => {
        const m = {};
        data.forEach(d => { m[d.locode] = d; });
        riskCache.current[key] = m;
        setRiskMap(m);
      })
      .catch(() => {});
  }, [sliderIdx]);

  const curMonth = ALL_MONTHS[sliderIdx];
  const shock = SHOCK_EVENTS.find(e => e.year === curMonth.year && e.month === curMonth.month);

  const getPortRisk = useCallback((locode) => {
    return riskMap[locode] || ports.find(p => p.locode === locode) || { risk_score: 20, risk_label: 'green', delay_prob: 0.2 };
  }, [riskMap, ports]);

  if (error) return (
    <div className="flex-1 flex items-center justify-center bg-gray-950">
      <div className="text-center">
        <div className="text-red-400 text-lg mb-2">API Unavailable</div>
        <div className="text-gray-500 text-sm">{error}</div>
        <div className="text-gray-600 text-xs mt-2">Start: uvicorn api.main:app --port 8000</div>
      </div>
    </div>
  );

  if (loading) return (
    <div className="flex-1 flex items-center justify-center bg-gray-950">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <div className="text-gray-400 text-sm">Loading port data…</div>
      </div>
    </div>
  );

  return (
    <div className="flex-1 relative flex flex-col">
      {/* Map */}
      <div className="flex-1 relative">
        <Map
          initialViewState={{ longitude: 20, latitude: 20, zoom: 1.8 }}
          mapStyle={MAP_STYLE}
          style={{ width: '100%', height: '100%' }}
          attributionControl={false}
        >
          <NavigationControl position="top-right" />

          {ports.map(port => {
            const risk = getPortRisk(port.locode);
            const color = scoreToColor(risk.risk_score ?? port.risk_score ?? 20);
            const r = tierToRadius(port.teu_tier);
            return (
              <Marker
                key={port.locode}
                longitude={port.lon}
                latitude={port.lat}
                anchor="center"
                onClick={e => { e.originalEvent.stopPropagation(); onPortSelect(port.locode); }}
              >
                <div
                  className="cursor-pointer transition-transform hover:scale-125"
                  onMouseEnter={() => setTooltip({ ...port, risk })}
                  onMouseLeave={() => setTooltip(null)}
                >
                  <svg width={r * 2 + 4} height={r * 2 + 4}>
                    <circle
                      cx={r + 2} cy={r + 2} r={r}
                      fill={color} fillOpacity={0.75}
                      stroke={color} strokeWidth={1.5}
                    />
                  </svg>
                </div>
              </Marker>
            );
          })}
        </Map>

        {/* Tooltip */}
        {tooltip && (
          <div className="absolute top-4 left-4 bg-gray-900/95 border border-gray-700 rounded-lg p-3 pointer-events-none z-10 min-w-[180px]">
            <div className="text-white font-semibold text-sm">{tooltip.port_name}</div>
            <div className="text-gray-400 text-xs mb-2">{tooltip.country} · {tooltip.locode}</div>
            <div className="flex items-center justify-between">
              <RiskBadge label={tooltip.risk?.risk_label || 'green'} score={tooltip.risk?.risk_score} />
              <span className="text-gray-400 text-xs">P(delay) {((tooltip.risk?.delay_prob || 0) * 100).toFixed(0)}%</span>
            </div>
          </div>
        )}

        {/* Legend */}
        <div className="absolute bottom-20 right-4 bg-gray-900/90 border border-gray-700 rounded-lg p-3 text-xs">
          <div className="text-gray-400 mb-2 font-medium">Risk Level</div>
          {[['green','Low'],['amber','Medium'],['red','High']].map(([c,l]) => (
            <div key={c} className="flex items-center gap-2 mb-1">
              <div className="w-3 h-3 rounded-full" style={{ background: scoreToColor(c === 'green' ? 10 : c === 'amber' ? 50 : 80) }} />
              <span className="text-gray-300">{l}</span>
            </div>
          ))}
          <div className="border-t border-gray-700 mt-2 pt-2 text-gray-500">
            Circle size = TEU volume
          </div>
        </div>
      </div>

      {/* Timeline slider */}
      <div className="bg-gray-900 border-t border-gray-800 px-6 py-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-gray-300 font-mono text-sm font-semibold">{curMonth.label}</span>
          {shock && (
            <span className="text-amber-400 text-xs bg-amber-900/30 border border-amber-800 px-2 py-0.5 rounded-full animate-pulse">
              ⚡ {shock.label}
            </span>
          )}
          <span className="text-gray-500 text-xs">{ports.length} ports tracked</span>
        </div>
        <input
          type="range"
          min={0}
          max={ALL_MONTHS.length - 1}
          value={sliderIdx}
          onChange={e => setSliderIdx(Number(e.target.value))}
          className="w-full h-1.5 bg-gray-700 rounded-full appearance-none cursor-pointer accent-blue-500"
        />
        <div className="flex justify-between text-gray-600 text-xs mt-1.5">
          <span>2020</span><span>2021</span><span>2022</span><span>2023</span><span>2024</span>
        </div>

        {/* Shock markers */}
        <div className="relative mt-1 h-3">
          {SHOCK_EVENTS.map(e => {
            const idx = ALL_MONTHS.findIndex(m => m.year === e.year && m.month === e.month);
            const pct = (idx / (ALL_MONTHS.length - 1)) * 100;
            return (
              <div
                key={`${e.year}-${e.month}`}
                className="absolute transform -translate-x-1/2"
                style={{ left: `${pct}%` }}
                title={e.label}
              >
                <div className="w-0.5 h-2 bg-amber-500/60" />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
