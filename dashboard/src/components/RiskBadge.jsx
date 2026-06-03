import { RISK_COLORS } from '../utils/colors';

const BG = { green: 'bg-green-900/40', amber: 'bg-amber-900/40', red: 'bg-red-900/40' };
const TEXT = { green: 'text-green-400', amber: 'text-amber-400', red: 'text-red-400' };
const BORDER = { green: 'border-green-500/40', amber: 'border-amber-500/40', red: 'border-red-500/40' };

export default function RiskBadge({ label, score }) {
  const l = label || 'green';
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${BG[l]} ${TEXT[l]} ${BORDER[l]}`}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: RISK_COLORS[l] }} />
      {score !== undefined ? `${Math.round(score)}` : l.toUpperCase()}
    </span>
  );
}
