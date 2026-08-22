import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';
import { X } from '@phosphor-icons/react';
import { getPort, onColdStart } from '../api';
import RiskBadge from './RiskBadge';
import { RISK_COLORS } from '../utils/colors';

function SectionLabel({ children, className = 'mb-3' }) {
  return (
    <h3 className={`text-ink-dim text-[10px] font-semibold uppercase tracking-[0.08em] ${className}`}>
      {children}
    </h3>
  );
}

/* Skeletons mirror the final layout, not a spinner in a void */
function DrilldownSkeleton() {
  return (
    <div className="flex-1 overflow-hidden px-5 py-4 space-y-5" aria-label="Loading port details" role="status">
      <div className="grid grid-cols-2 gap-2.5">
        {[0,1,2,3].map(i => <div key={i} className="skeleton h-[58px]" />)}
      </div>
      <div className="skeleton h-[120px]" />
      <div className="space-y-2.5">
        {[0,1,2,3,4].map(i => <div key={i} className="skeleton h-4" />)}
      </div>
    </div>
  );
}

export default function PortDrilldown({ portCode, onClose }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const [waking,  setWaking]  = useState(false);

  // Drilldown detail is one of the few things still fetched live, so a cold
  // backend can stall it; say so rather than showing a skeleton indefinitely.
  useEffect(() => onColdStart(setWaking), []);

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
    <div className="panel-enter w-full md:w-96 bg-hull border-l hairline flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b hairline shrink-0">
        <div className="min-w-0">
          {data ? (
            <>
              <h2 className="text-ink font-semibold text-[15px] truncate">{data.port_name}</h2>
              <p className="text-ink-mute text-[11px] font-mono">{data.country} · {data.locode}</p>
            </>
          ) : (
            <div className="skeleton h-9 w-40" />
          )}
        </div>
        <button
          onClick={onClose}
          aria-label="Close port details"
          className="pressable text-ink-dim hover:text-ink hover:bg-hull-2 rounded-md p-1.5 -mr-1.5"
        >
          <X size={16} weight="bold" />
        </button>
      </div>

      {loading && (
        <>
          {waking && (
            <div className="px-5 pt-4 text-ink-dim text-[11px] leading-relaxed">
              Waking the API — first request after idle can take up to a minute.
            </div>
          )}
          <DrilldownSkeleton />
        </>
      )}

      {error && (
        <div className="flex-1 flex items-center justify-center text-risk-high text-[13px]">{error}</div>
      )}

      {data && !loading && (
        <div className="flex-1 overflow-y-auto">
          {/* Current risk */}
          <div className="px-5 py-4 border-b hairline">
            <div className="flex items-center justify-between mb-3">
              <SectionLabel className="">Current risk</SectionLabel>
              <RiskBadge label={data.current_risk.risk_label} score={data.current_risk.risk_score} />
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              {[
                ['Delay prob', `${(data.current_risk.delay_prob * 100).toFixed(1)}%`],
                ['Exp. delay', `${data.current_risk.delay_days_pred?.toFixed(1)}d`],
                ['CPPI 2024', data.cppi_2024 !== null ? Math.round(data.cppi_2024) : 'N/A'],
                ['LPI score', data.lpi_score?.toFixed(2)],
              ].map(([k, v]) => (
                <div key={k} className="bg-hull-2 rounded-lg px-3 py-2.5">
                  <div className="text-ink-dim text-[10px] uppercase tracking-wider">{k}</div>
                  <div className="text-ink font-mono font-semibold text-[14px] mt-1 tabular-nums">{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Delay history */}
          <div className="px-5 py-4 border-b hairline">
            <SectionLabel>12-month delay rate</SectionLabel>
            {historyData.length > 0 ? (
              <ResponsiveContainer width="100%" height={120}>
                <BarChart data={historyData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <XAxis dataKey="label" tick={{ fill: '#5a6e80', fontSize: 9, fontFamily: 'IBM Plex Mono' }} interval={2} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: '#5a6e80', fontSize: 9, fontFamily: 'IBM Plex Mono' }} domain={[0, 100]} tickLine={false} axisLine={false} />
                  <Tooltip
                    cursor={{ fill: 'rgba(150,184,215,0.06)' }}
                    contentStyle={{ background: '#0d1420', border: '1px solid rgba(150,184,215,0.15)', borderRadius: 8, fontSize: 11 }}
                    labelStyle={{ color: '#8aa0b4', fontSize: 11, fontFamily: 'IBM Plex Mono' }}
                    formatter={(v, n) => [n === 'delay_rate' ? `${v}%` : `${v}d`, n === 'delay_rate' ? 'Delay rate' : 'Avg delay']}
                  />
                  <ReferenceLine y={35} stroke="rgba(150,184,215,0.18)" strokeDasharray="3 3" />
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
              <div className="text-ink-dim text-[12px] text-center py-4">No history data</div>
            )}
          </div>

          {/* SHAP waterfall */}
          <div className="px-5 py-4 border-b hairline">
            <SectionLabel>
              Why this risk score <span className="text-ink-dim font-normal normal-case">(SHAP)</span>
            </SectionLabel>
            {shapData.length > 0 ? (
              <div className="space-y-2">
                {shapData.map((s, i) => {
                  const isPositive = s.value > 0;
                  const maxAbs = Math.max(...shapData.map(x => Math.abs(x.value)));
                  const pct = maxAbs > 0 ? Math.abs(s.value) / maxAbs * 100 : 0;
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <div className="text-ink-mute text-[11px] w-28 truncate shrink-0" title={s.feature}>{s.feature}</div>
                      <div className="flex-1 relative h-3.5 bg-hull-2 rounded-sm overflow-hidden">
                        <div
                          className="absolute top-0 bottom-0 rounded-sm transition-[width] duration-300 ease-out"
                          style={{
                            width: `${pct}%`,
                            background: isPositive ? RISK_COLORS.red : RISK_COLORS.green,
                            left: isPositive ? 0 : undefined,
                            right: isPositive ? undefined : 0,
                            opacity: 0.85,
                          }}
                        />
                      </div>
                      <div className="text-[11px] w-14 text-right font-mono tabular-nums"
                           style={{ color: isPositive ? RISK_COLORS.red : RISK_COLORS.green }}>
                        {isPositive ? '+' : ''}{s.value.toFixed(3)}
                      </div>
                    </div>
                  );
                })}
                <p className="text-ink-dim text-[11px] mt-2.5">Red pushes risk up · green pulls it down</p>
              </div>
            ) : (
              <div className="text-ink-dim text-[12px] text-center py-4">No SHAP data</div>
            )}
          </div>

          {/* Port meta */}
          <div className="px-5 py-4">
            <SectionLabel>Port info</SectionLabel>
            <div className="space-y-2 text-[12px]">
              {[
                ['Region', data.region?.replace('_', ' ')],
                ['TEU tier', ['', 'Major hub (>30M TEU)', 'Secondary (10–30M TEU)', 'Regional (<10M TEU)'][data.teu_tier]],
                ['LSCI score', data.lsci_score?.toFixed(1)],
                ['Coordinates', `${data.lat?.toFixed(2)}°, ${data.lon?.toFixed(2)}°`],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4">
                  <span className="text-ink-dim">{k}</span>
                  <span className="text-ink-mute capitalize text-right font-mono">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
