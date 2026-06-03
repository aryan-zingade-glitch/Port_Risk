export const RISK_COLORS = {
  green: '#22c55e',
  amber: '#f59e0b',
  red:   '#ef4444',
};

export function scoreToLabel(score) {
  if (score < 34) return 'green';
  if (score < 67) return 'amber';
  return 'red';
}

export function labelToColor(label) {
  return RISK_COLORS[label] || RISK_COLORS.green;
}

export function scoreToColor(score) {
  return labelToColor(scoreToLabel(score));
}

export function tierToRadius(tier) {
  return tier === 1 ? 14 : tier === 2 ? 10 : 7;
}
