import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Render's free tier spins the service down after ~15 min idle, so the first
// request of a session has to cold-boot the container (deps + model load).
// That takes far longer than a normal request, and Render answers with 502/503
// or just hangs while it happens. Retry through it instead of reporting the
// backend as dead.
const REQUEST_TIMEOUT = 20000;
const COLD_START_RETRIES = 5;
const RETRY_DELAY = 3000;

const api = axios.create({ baseURL: BASE, timeout: REQUEST_TIMEOUT });

const coldStartListeners = new Set();

/** Subscribe to cold-start notifications. Returns an unsubscribe fn. */
export function onColdStart(fn) {
  coldStartListeners.add(fn);
  return () => coldStartListeners.delete(fn);
}

const notifyColdStart = (waking) => coldStartListeners.forEach(fn => fn(waking));

const sleep = ms => new Promise(r => setTimeout(r, ms));

// A timeout, a dropped connection, or a gateway error all mean "server isn't
// answering yet" — the signature of a boot in progress. A 4xx is a real error.
const isWaking = (err) =>
  err.code === 'ECONNABORTED' ||
  err.code === 'ERR_NETWORK' ||
  !err.response ||
  err.response.status === 502 ||
  err.response.status === 503 ||
  err.response.status === 504;

async function withRetry(fn) {
  let notified = false;
  for (let attempt = 0; ; attempt++) {
    try {
      const result = await fn();
      if (notified) notifyColdStart(false);
      return result;
    } catch (err) {
      if (attempt >= COLD_START_RETRIES || !isWaking(err)) {
        if (notified) notifyColdStart(false);
        throw err;
      }
      if (!notified) { notified = true; notifyColdStart(true); }
      await sleep(RETRY_DELAY);
    }
  }
}

// --- Static snapshot -------------------------------------------------------
// The map's data is historical and immutable, so it ships as a build artifact
// served off the same CDN as the app (see utils/build_snapshot.py). The map
// draws from this instantly, with no dependency on the sleeping backend.
let snapshotPromise = null;

export function getSnapshot() {
  if (!snapshotPromise) {
    snapshotPromise = fetch(`${import.meta.env.BASE_URL}snapshot.json`)
      .then(r => {
        if (!r.ok) throw new Error(`snapshot ${r.status}`);
        return r.json();
      })
      .catch(err => { snapshotPromise = null; throw err; });
  }
  return snapshotPromise;
}

/**
 * Nudge the backend awake without blocking anything. Called on app start so the
 * container is booting while the user reads the map, and the live-only views
 * (drilldown, route simulation) are warm by the time they're opened.
 */
export function wakeApi() {
  api.get('/health', { timeout: 120000 }).catch(() => {});
}

export const getPorts       = ()            => withRetry(() => api.get('/ports').then(r => r.data));
export const getPort        = (code)        => withRetry(() => api.get(`/ports/${code}`).then(r => r.data));
export const getRiskScores  = (year, month) => withRetry(() => api.get(`/risk-scores/${year}/${month}`).then(r => r.data));
export const getRoute       = (o, d)        => withRetry(() => api.get(`/route/${o}/${d}`).then(r => r.data));
