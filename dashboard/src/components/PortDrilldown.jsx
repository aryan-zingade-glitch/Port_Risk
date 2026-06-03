import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';
import { getPort } from '../api';
import RiskBadge from './RiskBadge';
import { RISK_COLORS } from '../utils/colors';

const MONTH_LABELS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

export default function PortDrilldown({ portCode, onClose }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    if (!portCode) return;
    setLoading(true); setError(null); setData(null);
    getPort(portCode)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => { setError('Failed to load port data'); setLoading(false); });
  }, [portCode]);

  const historyData = data?.history_12m?.map(h => ({
    label: `${String(h.month).padStart(2,'0')}/${String(h.year).slice(-2)}`,
    delay_rate:  Math.round(h.delay_rate * 100),
    mean_delay:  h.mean_delay_days,
    risk_score:  h.risk_score,
  })) || [];

  const shapData = data?.shap_waterfall?.slice(0, 8).map(s => ({
    feature: s.feature.replace(/_/g, ' ').replace('score clipped', '').replace('port ', ''),
    value:   s.shap_value,
    fval:    s.feature_value,
  })) || [];

  return (
    <div className="w-full md:w-96 bg-gray-900 border-l border-gray-800 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
        <div>
          {data ? (
            <>
              <h2 className="text-white font-semibold text-base">{data.port_name}</h2>
              <p className="text-gray-400 text-xs">{data.country} · {data.locode}</p>
            </>
          ) : (
            <div className="h-8 w-40 bg-gray-800 rounded animate-pulse" />
          )}
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors text-xl">✕</button>
      </div>

      {loading && (
        <div className="flex-1 flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {error && (
        <div className="flex-1 flex items-center justify-center text-red-400 text-sm">{error}</div>
      )}

      {data && !loading && (
        <div className="flex-1 overflow-y-auto">
          {/* Current risk */}
          <div className="px-5 py-4 border-b border-gray-800">
            <div className="flex items-center justify-between mb-3">
              <span className="text-gray-400 text-xs uppercase tracking-wide">Current Risk</span>
              <RiskBadge label={data.current_risk.risk_label} score={data.current_risk.risk_score} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                ['Delay Prob', `${(data.current_risk.delay_prob * 100).toFixed(1)}%`],
                ['Exp. Delay', `${data.current_risk.delay_days_pred?.toFixed(1)}d`],
                ['CPPI 2024', data.cppi_2024 !== null ? Math.round(data.cppi_2024) : 'N/A'],
                ['LPI Score', data.lpi_score?.toFixed(2)],
              ].map(([k, v]) => (
                <div key={k} className="bg-gray-800 rounded-lg p-2.5">
                  <div className="text-gray-500 text-xs">{k}</div>
                  <div className="text-white font-semibold text-sm mt-0.5">{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Delay history */}
          <div className="px-5 py-4 border-b border-gray-800">
            <h3 className="text-gray-300 text-xs uppercase tracking-wide mb-3">12-Month Delay Rate</h3>
            {historyData.length > 0 ? (
              <ResponsiveContainer width="100%" height={120}>
                <BarChart data={historyData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <XAxis dataKey="label" tick={{ fill: '#6b7280', fontSize: 9 }} interval={2} />
                  <YAxis tick={{ fill: '#6b7280', fontSize: 9 }} domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                    labelStyle={{ color: '#d1d5db', fontSize: 11 }}
                    formatter={(v, n) => [n === 'delay_rate' ? `${v}%` : `${v}d`, n === 'delay_rate' ? 'Delay rate' : 'Avg delay']}
                  />
                  <ReferenceLine y={35} stroke="#374151" strokeDasharray="3 3" />
                  <Bar dataKey="delay_rate" radius={[2,2,0,0]}>
                    {historyData.map((entry, i) => (
                      <Cell key={i} fill={
                        entry.delay_rate > 60 ? RISK_COLORS.red :
                        entry.delay_rate > 40 ? RISK_COLORS.amber :
                        RISK_COLORS.green
                      } />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-gray-600 text-xs text-center py-4">No history data</div>
            )}
          </div>

          {/* SHAP waterfall */}
          <div className="px-5 py-4 border-b border-gray-800">
            <h3 className="text-gray-300 text-xs uppercase tracking-wide mb-3">
              Why this risk score
              <span className="text-gray-600 font-normal ml-1">(SHAP)</span>
            </h3>
            {shapData.length > 0 ? (
              <div className="space-y-2">
                {shapData.map((s, i) => {
                  const isPositive = s.value > 0;
                  const maxAbs = Math.max(...shapData.map(x => Math.abs(x.value)));
                  const pct = maxAbs > 0 ? Math.abs(s.value) / maxAbs * 100 : 0;
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <div className="text-gray-400 text-xs w-28 truncate flex-shrink-0" title={s.feature}>{s.feature}</div>
                      <div className="flex-1 relative h-4 bg-gray-800 rounded-sm overflow-hidden">
                        <div
                          className="absolute top-0 bottom-0 rounded-sm transition-all"
                          style={{
                            width: `${pct}%`,
                            background: isPositive ? '#ef4444' : '#22c55e',
                            left: isPositive ? 0 : undefined,
                            right: isPositive ? undefined : 0,
                          }}
                        />
                      </div>
                      <div className={`text-xs w-14 text-right font-mono ${isPositive ? 'text-red-400' : 'text-green-400'}`}>
                        {isPositive ? '+' : ''}{s.value.toFixed(3)}
                      </div>
                    </div>
                  );
                })}
                <p className="text-gray-600 text-xs mt-2">Red = increases delay risk · Green = reduces it</p>
              </div>
            ) : (
              <div className="text-gray-600 text-xs text-center py-4">No SHAP data</div>
            )}
          </div>

          {/* Port meta */}
          <div className="px-5 py-4">
            <h3 className="text-gray-300 text-xs uppercase tracking-wide mb-3">Port Info</h3>
            <div className="space-y-2 text-xs">
              {[
                ['Region', data.region?.replace('_', ' ')],
                ['TEU Tier', ['', 'Major Hub (>30M TEU)', 'Secondary (10-30M TEU)', 'Regional (<10M TEU)'][data.teu_tier]],
                ['LSCI Score', data.lsci_score?.toFixed(1)],
                ['Coordinates', `${data.lat?.toFixed(2)}°, ${data.lon?.toFixed(2)}°`],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-gray-500">{k}</span>
                  <span className="text-gray-300 capitalize">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
