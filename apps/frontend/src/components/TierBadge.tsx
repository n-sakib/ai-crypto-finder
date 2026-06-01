import { Shield, TrendingUp, Wallet, Users } from 'lucide-react';

const TIER: Record<string, { bg: string; text: string; border: string; label: string }> = {
  tier_a: { bg: 'bg-green-500/10', text: 'text-green-500', border: 'border-green-500/20', label: 'Tier A' },
  tier_b: { bg: 'bg-indigo-500/10', text: 'text-indigo-400', border: 'border-indigo-500/20', label: 'Tier B' },
  tier_c: { bg: 'bg-zinc-500/10', text: 'text-zinc-400', border: 'border-zinc-500/20', label: 'Tier C' },
  excluded: { bg: 'bg-red-500/10', text: 'text-red-500', border: 'border-red-500/20', label: 'EXCLUDED' },
};

export default function TierBadge({ tier, risk }: { tier?: string | null; risk?: string | null }) {
  const t = TIER[tier || ''] || { bg: 'bg-zinc-500/10', text: 'text-zinc-400', border: 'border-zinc-500/20', label: tier || '—' };
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wide border ${t.bg} ${t.text} ${t.border}`}>
      {t.label}
      {risk && <span className={risk === 'critical' ? 'text-red-600' : risk === 'high' ? 'text-red-500' : risk === 'medium' ? 'text-yellow-500' : 'text-green-500'}>· {risk}</span>}
    </span>
  );
}

export function ScoreBar({ score, label, color = 'bg-indigo-500' }: { score: number; label: string; color?: string }) {
  const textColor = color.replace('bg-', 'text-');
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-[#71717a] w-24">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-[#1e1e2e]">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.min(score, 100)}%` }} />
      </div>
      <span className={`font-mono w-8 text-right ${textColor}`}>{score.toFixed(0)}</span>
    </div>
  );
}

export function MomentumBadge({ score }: { score: number }) {
  const c = score >= 65 ? '#22c55e' : score >= 45 ? '#6366f1' : score >= 20 ? '#f59e0b' : '#ef4444';
  const l = score >= 80 ? 'Very High' : score >= 65 ? 'High' : score >= 45 ? 'Strong' : score >= 20 ? 'Early' : 'Low';
  return (
    <div className="flex items-center gap-2">
      <div className="relative w-14 h-14 flex items-center justify-center">
        <svg className="absolute inset-0 w-full h-full -rotate-90" viewBox="0 0 56 56">
          <circle cx="28" cy="28" r="24" fill="none" stroke="#1e1e2e" strokeWidth="4" />
          <circle cx="28" cy="28" r="24" fill="none" stroke={c} strokeWidth="4" strokeDasharray={`${(score/100)*151} 151`} strokeLinecap="round" />
        </svg>
        <span className="relative text-lg font-bold" style={{ color: c }}>{score.toFixed(0)}</span>
      </div>
      <div>
        <div className="text-xs font-semibold" style={{ color: c }}>{l}</div>
        <div className="text-xs text-[#71717a]">Momentum</div>
      </div>
    </div>
  );
}

export function StatCard({ icon: Icon, label, value, color = 'text-indigo-400', bg = 'bg-indigo-500/10' }: {
  icon: React.ComponentType<{ size?: number }>; label: string; value: string | number; color?: string; bg?: string;
}) {
  return (
    <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-4 flex items-center gap-3">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${bg}`}><Icon size={18} className={color} /></div>
      <div><div className="text-xs text-[#71717a]">{label}</div><div className="text-lg font-bold text-[#e4e4e7]">{value}</div></div>
    </div>
  );
}
