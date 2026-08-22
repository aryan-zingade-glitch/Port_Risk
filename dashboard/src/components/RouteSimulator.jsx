import { useState, useEffect } from 'react';
import Map, { Marker, Source, Layer, NavigationControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Compass, ArrowDown } from '@phosphor-icons/react';
import { getSnapshot, getRoute, onColdStart } from '../api';
import { labelToColor } from '../utils/colors';
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
  malacca:   [103.8,   1.3],
  scs:       [115.0,  18.0],  // South China Sea — west of Philippines
  luzon_str: [124.0,  21.0],  // Luzon Strait / Bashi Channel (between Taiwan & Luzon)
  phil_sea:  [133.0,  20.0],  // Philippine Sea — east of Philippines, south of Japan
  hormuz:    [ 58.5,  22.0],
  bab:       [ 43.4,  12.6],
  red_sea:   [ 37.5,  21.0],
  med_e:     [ 28.0,  34.2],
  med_c:     [ 14.5,  37.0],
  gib:       [ -5.4,  36.0],
  atl_n:     [-25.0,  35.0],
  pac_mid:   [175.0,  10.0],  // mid-Pacific
  pac_e_uw:  [218.0,  15.0],  // ~142°W unwrapped — eastbound Pacific
  pac_w_ng:  [-150.0, 10.0],  // westbound Pacific
  pac_c_ng:  [-172.0,  5.0],
};

const inGulf = p => p.lat > 22 && p.lon > 48 && p.lon < 62;

// Returns intermediate ocean waypoints between two consecutive ports.
// The Philippines spans ~118–127°E, 5–21°N — most of the routing logic
// exists to steer lines around it via the South China Sea or Luzon Strait.
function segmentWaypoints(from, to) {
  const fr = from.region || '';
  const tr = to.region || '';

  // ── Asia-Pacific intra-region ──────────────────────────────────────────────
  if (fr === 'asia_pacific' && tr === 'asia_pacific') {
    const cross = (from.lon < 105 && to.lon >= 105) || (from.lon >= 105 && to.lon < 105);
    if (!cross) return [];

    // Determine which port is on the East Asian side (> 105°E)
    const eastPort = from.lon >= 105 ? from : to;
    const eastFirst = from.lon >= 105; // going East → West

    if (eastFirst) {
      // East Asia → South Asia: route west via South China Sea to avoid Philippines
      if (eastPort.lon > 120 && eastPort.lat > 18) return [N.scs, N.malacca];
      return [N.malacca];
    } else {
      // South Asia → East Asia: same corridor in reverse
      if (eastPort.lon > 120 && eastPort.lat > 18) return [N.malacca, N.scs];
      return [N.malacca];
    }
  }

  // ── Asia-Pacific ↔ Middle East ────────────────────────────────────────────
  if (fr === 'asia_pacific' && tr === 'middle_east')
    return from.lon >= 105 ? [N.malacca] : [];
  if (fr === 'middle_east' && tr === 'asia_pacific')
    return to.lon >= 105 ? [N.malacca] : [];

  // ── Middle East intra-region: Gulf / Red Sea corridor ────────────────────
  if (fr === 'middle_east' && tr === 'middle_east') {
    const fG = inGulf(from), tG = inGulf(to);
    if (fG && to.lon < 43)    return [N.hormuz, N.bab, N.red_sea];
    if (tG && from.lon < 43)  return [N.red_sea, N.bab, N.hormuz];
    if (from.lon > 43 && to.lon < 43) return [N.bab, N.red_sea];
    if (from.lon < 43 && to.lon > 43) return [N.red_sea, N.bab];
    return [];
  }

  // ── Middle East ↔ Europe: Suez / Mediterranean ───────────────────────────
  if (fr === 'middle_east' && tr === 'europe')
    return from.lon < 0 ? [] : [N.med_e, N.med_c, N.gib];
  if (fr === 'europe' && tr === 'middle_east')
    return to.lon < 0 ? [] : [N.gib, N.med_c, N.med_e];

  // ── Europe ↔ Americas: Atlantic crossing ─────────────────────────────────
  if (fr === 'europe' && tr === 'americas') return [N.gib, N.atl_n];
  if (fr === 'americas' && tr === 'europe') return [N.atl_n, N.gib];

  // ── Asia-Pacific → Americas: eastbound trans-Pacific ─────────────────────
  // Three sub-cases to avoid the Philippines:
  //   1. South/SW Asia (Mumbai, Colombo): enter Pacific via Malacca → equatorial
  //   2. N China, HK, Taiwan (lat>20, lon 105–122°E): exit via Luzon Strait
  //   3. Japan, Korea (lon ≥ 122°E): already in Philippine Sea, head east
  if (fr === 'asia_pacific' && tr === 'americas') {
    if (from.lon < 105) {
      return [N.malacca, N.pac_mid, N.pac_e_uw];
    }
    if (from.lat > 20 && from.lon < 123) {
      // N China coast / HK / Taiwan: north of Philippines, exit via Luzon Strait
      return [N.luzon_str, N.phil_sea, N.pac_mid, N.pac_e_uw];
    }
    if (from.lon >= 123) {
      // Japan / Korea: head south-east into Philippine Sea then Pacific
      return [N.phil_sea, N.pac_mid, N.pac_e_uw];
    }
    // SE Asia or Manila (lat < 20, lon 105–123): go east into Philippine Sea
    return [N.pac_mid, N.pac_e_uw];
  }

  // ── Americas → Asia-Pacific: westbound trans-Pacific ─────────────────────
  if (fr === 'americas' && tr === 'asia_pacific') {
    const wps = [N.pac_w_ng, N.pac_c_ng];
    if (to.lon < 105) wps.push(N.malacca);
    return wps;
  }

  // ── Middle East ↔ Americas: Suez → Med → Atlantic ────────────────────────
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

  // ── Asia-Pacific ↔ Europe: fallback (API should add intermediate ports) ──
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

function FieldLabel({ children, htmlFor }) {
  return (
    <label htmlFor={htmlFor} className="block text-ink-dim text-[10px] font-semibold uppercase tracking-[0.08em] mb-1.5">
      {children}
    </label>
  );
}

export default function RouteSimulator() {
  const [ports,    setPorts]   = useState([]);
  const [origin,   setOrigin]  = useState('SGSIN');
  const [dest,     setDest]    = useState('NLRTM');
  const [result,   setResult]  = useState(null);
  const [loading,  setLoading] = useState(false);
  const [error,    setError]   = useState(null);
  const [portMap,  setPortMap] = useState({});
  const [waking,   setWaking]  = useState(false);

  // The API sleeps when idle; a slow call is a wake-up, not a failure.
  useEffect(() => onColdStart(setWaking), []);

  // Port list comes from the static snapshot so the selectors are usable the
  // moment the view opens. Only the simulation itself needs the live API.
  useEffect(() => {
    getSnapshot().then(({ ports: data }) => {
      setPorts(data);
      const m = {};
      data.forEach(p => { m[p.locode] = p; });
      setPortMap(m);
    }).catch(() => setError('Could not load port list.'));
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
      <div className="w-full md:w-80 bg-hull border-r hairline flex flex-col overflow-y-auto shrink-0">
        <div className="px-5 py-5 border-b hairline">
          <h2 className="text-ink font-semibold text-[15px] mb-1">Route Risk Simulator</h2>
          <p className="text-ink-mute text-[12px]">Cumulative delay risk along a shipping route</p>
        </div>

        <div className="px-5 py-4 space-y-4 border-b hairline">
          <div>
            <FieldLabel htmlFor="origin-select">Origin port</FieldLabel>
            <select
              id="origin-select"
              className="field"
              value={origin}
              onChange={e => setOrigin(e.target.value)}
            >
              {sortedPorts.map(p => (
                <option key={p.locode} value={p.locode}>{p.port_name} ({p.locode})</option>
              ))}
            </select>
          </div>

          <div className="flex justify-center -my-2">
            <ArrowDown size={13} className="text-ink-dim" />
          </div>

          <div>
            <FieldLabel htmlFor="dest-select">Destination port</FieldLabel>
            <select
              id="dest-select"
              className="field"
              value={dest}
              onChange={e => setDest(e.target.value)}
            >
              {sortedPorts.map(p => (
                <option key={p.locode} value={p.locode}>{p.port_name} ({p.locode})</option>
              ))}
            </select>
          </div>

          <button
            onClick={simulate}
            disabled={loading || !origin || !dest || origin === dest}
            className="pressable w-full bg-signal-deep hover:bg-signal text-abyss font-semibold py-2.5 rounded-lg text-[13px]
                       disabled:bg-hull-2 disabled:text-ink-dim disabled:cursor-not-allowed"
          >
            {loading ? (waking ? 'Waking the API…' : 'Simulating…') : 'Simulate route'}
          </button>

          {error && <p className="text-risk-high text-[12px]">{error}</p>}
          {waking && !error && (
            <p className="text-ink-dim text-[11px] leading-relaxed">
              The backend sleeps when idle. This can take up to a minute.
            </p>
          )}
        </div>

        {/* Results */}
        {loading && (
          <div className="px-5 py-4 space-y-3" role="status" aria-label="Simulating route">
            <div className="skeleton h-[140px]" />
            <div className="skeleton h-5 w-2/3" />
            <div className="skeleton h-12" />
            <div className="skeleton h-12" />
          </div>
        )}

        {result && !loading && (
          <div className="panel-enter px-5 py-4 space-y-5">
            {/* Summary */}
            <div className="bg-hull-2 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-ink text-[13px] font-semibold">Route summary</span>
                <RiskBadge label={result.route_risk_label} score={result.route_risk_score} />
              </div>
              <div className="grid grid-cols-2 gap-2 text-[12px]">
                {[
                  ['Total delay risk', `${(result.cumulative_delay_prob * 100).toFixed(1)}%`],
                  ['Expected delay',   `${result.expected_total_delay_days?.toFixed(1)}d`],
                  ['Voyage time',      `${result.base_voyage_days?.toFixed(1)}d`],
                  ['ETA (with delay)', formatETA(result.base_voyage_days, result.expected_total_delay_days)],
                  ['Waypoints',        result.waypoints.length],
                  ['Ports touched',    result.all_ports.length],
                ].map(([k, v]) => (
                  <div key={k} className="bg-abyss/50 rounded-lg px-2.5 py-2">
                    <div className="text-ink-dim text-[10px] uppercase tracking-wider">{k}</div>
                    <div className="text-ink font-mono font-semibold mt-1 tabular-nums">{v}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Waypoints */}
            {result.waypoints.length > 0 && (
              <div>
                <FieldLabel>Routing via</FieldLabel>
                <div className="flex flex-wrap gap-1.5">
                  {result.waypoints.map((lc, i) => (
                    <span key={i} className="bg-hull-2 border hairline text-ink-mute text-[11px] px-2 py-1 rounded-md">
                      {result.waypoint_names[i]}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Segments */}
            <div>
              <FieldLabel>Segment risk</FieldLabel>
              <div className="space-y-1.5">
                {result.segments.map((seg, i) => (
                  <div key={i} className="flex items-center gap-3 bg-hull-2 rounded-lg px-3 py-2">
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ background: labelToColor(seg.risk_label) }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-ink text-[12px] font-medium truncate">{seg.from_name}</div>
                      <div className="text-ink-dim text-[11px] font-mono">P(delay) {(seg.delay_prob * 100).toFixed(0)}%</div>
                    </div>
                    <span className="text-ink-mute text-[12px] font-mono tabular-nums">{Math.round(seg.risk_score)}</span>
                  </div>
                ))}
                {/* Destination */}
                <div className="flex items-center gap-3 bg-hull-2 rounded-lg px-3 py-2">
                  <span className="w-2 h-2 rounded-full shrink-0 bg-ink-dim" />
                  <div className="flex-1 min-w-0">
                    <div className="text-ink-mute text-[12px] font-medium truncate">{result.destination_name}</div>
                    <div className="text-ink-dim text-[11px]">Destination</div>
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
                  'line-color': '#56c8d8',
                  'line-width': 2.5,
                  'line-opacity': 0.85,
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
            const color = seg ? labelToColor(seg.risk_label) : '#5a6e80';
            const isEndpoint = i === 0 || i === result.all_ports.length - 1;
            return (
              <Marker key={lc} longitude={p.lon} latitude={p.lat} anchor="center">
                <div className="relative">
                  <svg width={isEndpoint ? 20 : 14} height={isEndpoint ? 20 : 14}>
                    <circle
                      cx={isEndpoint ? 10 : 7} cy={isEndpoint ? 10 : 7}
                      r={isEndpoint ? 9 : 6}
                      fill={color} fillOpacity={0.85}
                      stroke="#e6edf3" strokeWidth={isEndpoint ? 2 : 1}
                    />
                  </svg>
                  {isEndpoint && (
                    <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-ink text-[11px] font-mono font-medium whitespace-nowrap bg-hull/90 border hairline px-1.5 py-0.5 rounded">
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
            <div className="text-center bg-abyss/70 backdrop-blur-sm border hairline rounded-xl px-8 py-6">
              <Compass size={28} className="text-signal mx-auto mb-3" />
              <div className="text-ink text-[13px] font-medium mb-0.5">Plot a route</div>
              <div className="text-ink-mute text-[12px]">Pick origin and destination ports,<br />then simulate to see cumulative risk</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
