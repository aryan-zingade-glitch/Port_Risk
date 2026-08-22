import { useState, useEffect, useCallback, useRef } from 'react';
import Map, { Marker, NavigationControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Warning, Lightning } from '@phosphor-icons/react';
import { getSnapshot } from '../api';
import { scoreToColor, tierToRadius } from '../utils/colors';
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

  // Ports and every month of risk scores ship with the app as a static
  // snapshot, so the map draws immediately off the CDN rather than waiting on
  // the backend to wake up. Scrubbing the timeline stays instant too.
  useEffect(() => {
    getSnapshot()
      .then(({ ports, riskScores }) => {
        setPorts(ports);
        riskCache.current = riskScores;
        setLoading(false);
      })
      .catch(() => setError('Could not load map data. Try reloading the page.'));
  }, []);

  // Swap in the month the slider points at.
  useEffect(() => {
    const { year, month } = ALL_MONTHS[sliderIdx];
    setRiskMap(riskCache.current[`${year}-${month}`] || {});
  }, [sliderIdx, loading]);

  const curMonth = ALL_MONTHS[sliderIdx];
  const shock = SHOCK_EVENTS.find(e => e.year === curMonth.year && e.month === curMonth.month);

  const getPortRisk = useCallback((locode) => {
    return riskMap[locode] || ports.find(p => p.locode === locode) || { risk_score: 20, risk_label: 'green', delay_prob: 0.2 };
  }, [riskMap, ports]);

  if (error) return (
    <div className="flex-1 flex items-center justify-center bg-abyss">
      <div className="text-center max-w-xs">
        <Warning size={28} className="text-risk-high mx-auto mb-3" />
        <div className="text-ink text-[15px] font-semibold mb-1">Map data unavailable</div>
        <div className="text-ink-mute text-[13px]">{error}</div>
      </div>
    </div>
  );

  if (loading) return (
    <div className="flex-1 flex items-center justify-center bg-abyss">
      <div className="text-center">
        <div className="radar mx-auto mb-4" role="status" aria-label="Loading port data" />
        <div className="text-ink-mute text-[13px]">Scanning port network…</div>
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
                  className="cursor-pointer transition-transform duration-150 ease-out hover:scale-125"
                  onMouseEnter={() => setTooltip({ ...port, risk })}
                  onMouseLeave={() => setTooltip(null)}
                >
                  <svg width={r * 2 + 4} height={r * 2 + 4}>
                    <circle
                      cx={r + 2} cy={r + 2} r={r}
                      fill={color} fillOpacity={0.7}
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
          <div className="overlay-enter absolute top-4 left-4 bg-hull/95 backdrop-blur-sm border hairline rounded-lg p-3 pointer-events-none z-10 min-w-[190px] shadow-lg shadow-black/30">
            <div className="text-ink font-semibold text-[13px]">{tooltip.port_name}</div>
            <div className="text-ink-mute text-[11px] font-mono mb-2">{tooltip.country} · {tooltip.locode}</div>
            <div className="flex items-center justify-between gap-3">
              <RiskBadge label={tooltip.risk?.risk_label || 'green'} score={tooltip.risk?.risk_score} />
              <span className="text-ink-mute text-[11px] font-mono">P(delay) {((tooltip.risk?.delay_prob || 0) * 100).toFixed(0)}%</span>
            </div>
          </div>
        )}

        {/* Legend */}
        <div className="absolute bottom-24 right-4 bg-hull/90 backdrop-blur-sm border hairline rounded-lg px-3 py-2.5 text-[11px]">
          <div className="text-ink-dim uppercase tracking-wider text-[10px] font-semibold mb-2">Risk level</div>
          {[['green','Low'],['amber','Medium'],['red','High']].map(([c,l]) => (
            <div key={c} className="flex items-center gap-2 mb-1.5 last:mb-0">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: scoreToColor(c === 'green' ? 10 : c === 'amber' ? 50 : 80) }} />
              <span className="text-ink-mute">{l}</span>
            </div>
          ))}
          <div className="border-t hairline mt-2 pt-2 text-ink-dim">
            Circle size = TEU volume
          </div>
        </div>
      </div>

      {/* Timeline */}
      <div className="bg-hull border-t hairline px-6 py-4 shrink-0">
        <div className="flex items-center justify-between mb-2.5">
          <span className="text-ink font-mono text-[15px] font-semibold tabular-nums">{curMonth.label}</span>
          {shock && (
            <span className="overlay-enter flex items-center gap-1.5 text-risk-mid text-[11px] font-medium bg-risk-mid/10 border border-risk-mid/30 px-2.5 py-1 rounded-md">
              <Lightning size={12} weight="fill" />
              {shock.label}
            </span>
          )}
          <span className="text-ink-dim text-[11px] font-mono">{ports.length} ports tracked</span>
        </div>
        <input
          type="range"
          className="timeline"
          min={0}
          max={ALL_MONTHS.length - 1}
          value={sliderIdx}
          onChange={e => setSliderIdx(Number(e.target.value))}
          aria-label="Month"
          aria-valuetext={curMonth.label}
        />
        <div className="flex justify-between text-ink-dim text-[11px] font-mono mt-1.5">
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
                className="absolute -translate-x-1/2"
                style={{ left: `${pct}%` }}
                title={e.label}
              >
                <div className="w-px h-2.5 bg-risk-mid/70" />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
