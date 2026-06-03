import { useState, useEffect } from 'react';
import Map, { Marker, Source, Layer, NavigationControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { getPorts, getRoute } from '../api';
import { scoreToColor, labelToColor, RISK_COLORS } from '../utils/colors';
import RiskBadge from './RiskBadge';

const MAP_STYLE = {
  version: 8,
  sources: {
    carto: {
      type: 'raster',
      tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'],
      tileSize: 256,
    },
  },
  layers: [{ id: 'carto-layer', type: 'raster', source: 'carto' }],
};

export default function RouteSimulator() {
  const [ports,    setPorts]   = useState([]);
  const [origin,   setOrigin]  = useState('SGSIN');
  const [dest,     setDest]    = useState('NLRTM');
  const [result,   setResult]  = useState(null);
  const [loading,  setLoading] = useState(false);
  const [error,    setError]   = useState(null);
  const [portMap,  setPortMap] = useState({});

  useEffect(() => {
    getPorts().then(data => {
      setPorts(data);
      const m = {};
      data.forEach(p => { m[p.locode] = p; });
      setPortMap(m);
    }).catch(() => setError('Cannot reach API'));
  }, []);

  const simulate = () => {
    if (!origin || !dest || origin === dest) return;
    setLoading(true); setError(null);
    getRoute(origin, dest)
      .then(r => { setResult(r); setLoading(false); })
      .catch(() => { setError('Route simulation failed'); setLoading(false); });
  };

  // Build GeoJSON line from route ports
  const routeGeoJSON = result ? {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: result.all_ports
          .map(lc => portMap[lc])
          .filter(Boolean)
          .map(p => [p.lon, p.lat]),
      },
      properties: {},
    }],
  } : null;

  const sortedPorts = [...ports].sort((a, b) => a.port_name.localeCompare(b.port_name));

  return (
    <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
      {/* Left: controls + results */}
      <div className="w-full md:w-80 bg-gray-900 border-r border-gray-800 flex flex-col overflow-y-auto">
        <div className="px-5 py-5 border-b border-gray-800">
          <h2 className="text-white font-semibold mb-1">Route Risk Simulator</h2>
          <p className="text-gray-500 text-xs">Analyse cumulative delay risk along a shipping route</p>
        </div>

        <div className="px-5 py-4 space-y-4 border-b border-gray-800">
          {/* Origin */}
          <div>
            <label className="block text-gray-400 text-xs mb-1.5 uppercase tracking-wide">Origin Port</label>
            <select
              value={origin}
              onChange={e => setOrigin(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
            >
              {sortedPorts.map(p => (
                <option key={p.locode} value={p.locode}>{p.port_name} ({p.locode})</option>
              ))}
            </select>
          </div>

          {/* Destination */}
          <div>
            <label className="block text-gray-400 text-xs mb-1.5 uppercase tracking-wide">Destination Port</label>
            <select
              value={dest}
              onChange={e => setDest(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
            >
              {sortedPorts.map(p => (
                <option key={p.locode} value={p.locode}>{p.port_name} ({p.locode})</option>
              ))}
            </select>
          </div>

          <button
            onClick={simulate}
            disabled={loading || !origin || !dest || origin === dest}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-semibold py-2.5 rounded-lg transition-colors text-sm"
          >
            {loading ? 'Simulating…' : 'Simulate Route'}
          </button>

          {error && <p className="text-red-400 text-xs">{error}</p>}
        </div>

        {/* Results */}
        {result && (
          <div className="px-5 py-4 space-y-4">
            {/* Summary */}
            <div className="bg-gray-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-gray-300 text-sm font-semibold">Route Summary</span>
                <RiskBadge label={result.route_risk_label} score={result.route_risk_score} />
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {[
                  ['Total delay risk', `${(result.cumulative_delay_prob * 100).toFixed(1)}%`],
                  ['Expected delay', `${result.expected_total_delay_days?.toFixed(1)}d`],
                  ['Waypoints', result.waypoints.length],
                  ['Ports touched', result.all_ports.length],
                ].map(([k, v]) => (
                  <div key={k} className="bg-gray-750 bg-gray-900/50 rounded-lg p-2">
                    <div className="text-gray-500">{k}</div>
                    <div className="text-white font-semibold mt-0.5">{v}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Waypoints */}
            {result.waypoints.length > 0 && (
              <div>
                <h3 className="text-gray-400 text-xs uppercase tracking-wide mb-2">Routing via</h3>
                <div className="flex flex-wrap gap-1.5">
                  {result.waypoints.map((lc, i) => (
                    <span key={i} className="bg-gray-800 border border-gray-700 text-gray-300 text-xs px-2 py-1 rounded-full">
                      {result.waypoint_names[i]}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Segments */}
            <div>
              <h3 className="text-gray-400 text-xs uppercase tracking-wide mb-2">Segment Risk</h3>
              <div className="space-y-2">
                {result.segments.map((seg, i) => (
                  <div key={i} className="flex items-center gap-3 bg-gray-800 rounded-lg px-3 py-2">
                    <div
                      className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                      style={{ background: labelToColor(seg.risk_label) }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-white text-xs font-medium truncate">{seg.from_name}</div>
                      <div className="text-gray-500 text-xs">P(delay): {(seg.delay_prob * 100).toFixed(0)}%</div>
                    </div>
                    <span className="text-gray-400 text-xs">{Math.round(seg.risk_score)}</span>
                  </div>
                ))}
                {/* Destination */}
                <div className="flex items-center gap-3 bg-gray-800 rounded-lg px-3 py-2">
                  <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: '#6b7280' }} />
                  <div className="flex-1 min-w-0">
                    <div className="text-gray-300 text-xs font-medium truncate">{result.destination_name}</div>
                    <div className="text-gray-500 text-xs">Destination</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Right: map */}
      <div className="flex-1 relative">
        <Map
          initialViewState={{ longitude: 20, latitude: 20, zoom: 1.8 }}
          mapStyle={MAP_STYLE}
          style={{ width: '100%', height: '100%' }}
          attributionControl={false}
        >
          <NavigationControl position="top-right" />

          {/* Route line */}
          {routeGeoJSON && (
            <Source id="route" type="geojson" data={routeGeoJSON}>
              <Layer
                id="route-line"
                type="line"
                paint={{
                  'line-color': '#3b82f6',
                  'line-width': 2.5,
                  'line-opacity': 0.8,
                  'line-dasharray': [4, 2],
                }}
              />
            </Source>
          )}

          {/* Port markers */}
          {result && result.all_ports.map((lc, i) => {
            const p = portMap[lc];
            if (!p) return null;
            const seg = result.segments.find(s => s.from_port === lc);
            const color = seg ? labelToColor(seg.risk_label) : '#6b7280';
            const isEndpoint = i === 0 || i === result.all_ports.length - 1;
            return (
              <Marker key={lc} longitude={p.lon} latitude={p.lat} anchor="center">
                <div className="relative">
                  <svg width={isEndpoint ? 20 : 14} height={isEndpoint ? 20 : 14}>
                    <circle
                      cx={isEndpoint ? 10 : 7} cy={isEndpoint ? 10 : 7}
                      r={isEndpoint ? 9 : 6}
                      fill={color} fillOpacity={0.8}
                      stroke="white" strokeWidth={isEndpoint ? 2 : 1}
                    />
                  </svg>
                  {isEndpoint && (
                    <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-white text-xs font-semibold whitespace-nowrap bg-gray-900/80 px-1.5 py-0.5 rounded">
                      {p.port_name}
                    </div>
                  )}
                </div>
              </Marker>
            );
          })}
        </Map>

        {!result && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center">
              <div className="text-4xl mb-3">🚢</div>
              <div className="text-gray-400 text-sm">Select origin and destination,<br />then simulate a route</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
