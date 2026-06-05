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

// ─── Sea-lane routing ────────────────────────────────────────────────────────

const N = {
  malacca:  [103.8,   1.3],
  hormuz:   [ 58.5,  22.0],
  bab:      [ 43.4,  12.6],
  red_sea:  [ 37.5,  21.0],
  med_e:    [ 28.0,  34.2],
  med_c:    [ 14.5,  37.0],
  gib:      [ -5.4,  36.0],
  atl_n:    [-25.0,  35.0],
  pac_w:    [130.0,  10.0],
  pac_c:    [172.0,   2.0],
  pac_e_uw: [220.0,  10.0],  // ~140°W unwrapped — eastbound Pacific
  pac_w_ng: [-150.0, 10.0],  // ~150°W — westbound Pacific
  pac_c_ng: [-172.0,  2.0],
};

const inGulf = p => p.lat > 22 && p.lon > 48 && p.lon < 62;

function segmentWaypoints(from, to) {
  const fr = from.region || '';
  const tr = to.region || '';

  if (fr === 'asia_pacific' && tr === 'asia_pacific') {
    const cross = (from.lon < 105 && to.lon >= 105) || (from.lon >= 105 && to.lon < 105);
    return cross ? [N.malacca] : [];
  }

  if (fr === 'asia_pacific' && tr === 'middle_east')
    return from.lon >= 105 ? [N.malacca] : [];
  if (fr === 'middle_east' && tr === 'asia_pacific')
    return to.lon >= 105 ? [N.malacca] : [];

  if (fr === 'middle_east' && tr === 'middle_east') {
    const fG = inGulf(from), tG = inGulf(to);
    if (fG && to.lon < 43)    return [N.hormuz, N.bab, N.red_sea];
    if (tG && from.lon < 43)  return [N.red_sea, N.bab, N.hormuz];
    if (from.lon > 43 && to.lon < 43) return [N.bab, N.red_sea];
    if (from.lon < 43 && to.lon > 43) return [N.red_sea, N.bab];
    return [];
  }

  if (fr === 'middle_east' && tr === 'europe')
    return from.lon < 0 ? [] : [N.med_e, N.med_c, N.gib];
  if (fr === 'europe' && tr === 'middle_east')
    return to.lon < 0 ? [] : [N.gib, N.med_c, N.med_e];

  if (fr === 'europe' && tr === 'americas') return [N.gib, N.atl_n];
  if (fr === 'americas' && tr === 'europe') return [N.atl_n, N.gib];

  if (fr === 'asia_pacific' && tr === 'americas') {
    const wps = from.lon < 105 ? [N.malacca] : [];
    wps.push(N.pac_w, N.pac_c, N.pac_e_uw);
    return wps;
  }
  if (fr === 'americas' && tr === 'asia_pacific') {
    const wps = [N.pac_w_ng, N.pac_c_ng];
    if (to.lon < 105) wps.push(N.malacca);
    return wps;
  }

  if (fr === 'middle_east' && tr === 'americas') {
    const wps = [];
    if (from.lon >= 0) {
      if (inGulf(from)) wps.push(N.hormuz, N.bab, N.red_sea);
      else if (from.lon > 43) wps.push(N.bab, N.red_sea);
      wps.push(N.med_e, N.med_c, N.gib);
    }
    wps.push(N.atl_n);
    return wps;
  }
  if (fr === 'americas' && tr === 'middle_east') {
    const wps = [N.atl_n];
    if (to.lon >= 0) {
      wps.push(N.gib, N.med_c, N.med_e);
      if (to.lon > 43) wps.push(N.red_sea, N.bab);
      if (inGulf(to)) wps.push(N.hormuz);
    }
    return wps;
  }

  if (fr === 'asia_pacific' && tr === 'europe')
    return [N.malacca, N.bab, N.red_sea, N.med_e, N.med_c, N.gib];
  if (fr === 'europe' && tr === 'asia_pacific')
    return [N.gib, N.med_c, N.med_e, N.red_sea, N.bab, N.malacca];

  return [];
}

function buildSeaRouteLine(allPorts, portMap) {
  const ps = allPorts.map(lc => portMap[lc]).filter(Boolean);
  if (ps.length < 2) return ps.map(p => [p.lon, p.lat]);

  // Eastbound trans-Pacific: unwrap western hemisphere lons to >180 so MapLibre
  // draws the line going east across the Pacific instead of westward through Africa.
  const transPacE = (ps[0].region === 'asia_pacific') && (ps[ps.length - 1].region === 'americas');
  const wLon = lon => (transPacE && lon < 0) ? lon + 360 : lon;

  const coords = [[wLon(ps[0].lon), ps[0].lat]];
  for (let i = 0; i < ps.length - 1; i++) {
    segmentWaypoints(ps[i], ps[i + 1]).forEach(([lo, la]) => coords.push([wLon(lo), la]));
    coords.push([wLon(ps[i + 1].lon), ps[i + 1].lat]);
  }
  return coords;
}

function formatETA(baseVoyageDays, expectedDelayDays) {
  const totalDays = Math.round((baseVoyageDays || 0) + (expectedDelayDays || 0));
  const eta = new Date(Date.now() + totalDays * 86_400_000);
  return eta.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

// ─────────────────────────────────────────────────────────────────────────────

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

  // Build GeoJSON line following actual ocean lanes (no straight displacement)
  const routeGeoJSON = result ? {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: buildSeaRouteLine(result.all_ports, portMap),
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
                  ['Expected delay',   `${result.expected_total_delay_days?.toFixed(1)}d`],
                  ['Voyage time',      `${result.base_voyage_days?.toFixed(1)}d`],
                  ['ETA (with delay)', formatETA(result.base_voyage_days, result.expected_total_delay_days)],
                  ['Waypoints',        result.waypoints.length],
                  ['Ports touched',    result.all_ports.length],
                ].map(([k, v]) => (
                  <div key={k} className="bg-gray-900/50 rounded-lg p-2">
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
