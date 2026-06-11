import { RISK_COLORS } from '../utils/colors';

const TEXT = {
  green: 'text-risk-low',
  amber: 'text-risk-mid',
  red:   'text-risk-high',
};
const TINT = {
  green: 'bg-risk-low/10 border-risk-low/30',
  amber: 'bg-risk-mid/10 border-risk-mid/30',
  red:   'bg-risk-high/10 border-risk-high/30',
};

export default function RiskBadge({ label, score }) {
  const l = label || 'green';
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-mono font-semibold border ${TINT[l]} ${TEXT[l]}`}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: RISK_COLORS[l] }} />
      {score !== undefined ? Math.round(score) : l.toUpperCase()}
    </span>
  );
}
