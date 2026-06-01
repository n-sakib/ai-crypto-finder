import { useState } from 'react';
import { TrendingUp, Shield, Wallet, AlertTriangle, PieChart, BarChart3, Info } from 'lucide-react';
import { PieChart as RePie, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, LabelList } from 'recharts';
import { useRankings, useStats } from '../hooks/useApi';
import TokenRow from '../components/TokenRow';
import { StatCard } from '../components/TierBadge';

const TABS = [
  { key: 'tier_a' as const, label: '🔥 Tier A', color: 'text-green-500', bg: 'bg-green-500/10', border: 'border-green-500/30', desc: 'Immediate review' },
  { key: 'tier_b' as const, label: '📊 Tier B', color: 'text-indigo-400', bg: 'bg-indigo-500/10', border: 'border-indigo-500/30', desc: 'Watch closely' },
  { key: 'tier_c' as const, label: '👀 Tier C', color: 'text-zinc-400', bg: 'bg-zinc-500/10', border: 'border-zinc-500/30', desc: 'Early signs' },
  { key: 'excluded' as const, label: '⚠️ Excluded', color: 'text-red-500', bg: 'bg-red-500/10', border: 'border-red-500/30', desc: 'High risk' },
];

const PIE_COLORS = ['#22c55e', '#6366f1', '#a1a1aa', '#ef4444'];

export default function Dashboard() {
  const { data: rankings } = useRankings();
  const { data: stats } = useStats();
  const [tab, setTab] = useState<'tier_a'|'tier_b'|'tier_c'|'excluded'>('tier_a');
  const tokens = rankings?.[tab] || [];

  // Pie chart data
  const pieData = [
    { name: 'Tier A', value: stats?.tier_a_count ?? rankings?.tier_a?.length ?? 0 },
    { name: 'Tier B', value: stats?.tier_b_count ?? rankings?.tier_b?.length ?? 0 },
    { name: 'Tier C', value: stats?.tier_c_count ?? rankings?.tier_c?.length ?? 0 },
    { name: 'Excluded', value: stats?.excluded_count ?? rankings?.excluded?.length ?? 0 },
  ].filter(d => d.value > 0);

  // Bar chart data — all ranked tokens sorted by momentum
  const allTokens = [
    ...(rankings?.tier_a || []),
    ...(rankings?.tier_b || []),
    ...(rankings?.tier_c || []),
  ].sort((a, b) => b.early_momentum_score - a.early_momentum_score);

  const barData = allTokens.map(t => ({
    name: t.symbol,
    score: Math.round(t.early_momentum_score),
    tier: t.tier?.replace('tier_', '').toUpperCase() || '?',
  }));

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[#e4e4e7]">Token Rankings</h1>
          <p className="text-sm mt-1 text-[#71717a]">{rankings?.total_candidates||0} candidates</p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <StatCard icon={TrendingUp} label="Tier A" value={stats?.tier_a_count ?? rankings?.tier_a?.length ?? 0} color="text-green-500" bg="bg-green-500/10"/>
        <StatCard icon={Shield} label="Tier B" value={stats?.tier_b_count ?? rankings?.tier_b?.length ?? 0} color="text-indigo-400" bg="bg-indigo-500/10"/>
        <StatCard icon={Wallet} label="Total Ranked" value={stats?.tokens_ranked ?? rankings?.total_candidates ?? 0} color="text-yellow-500" bg="bg-yellow-500/10"/>
        <StatCard icon={AlertTriangle} label="Excluded" value={stats?.excluded_count ?? rankings?.excluded?.length ?? 0} color="text-red-500" bg="bg-red-500/10"/>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Pie Chart — Tier Distribution */}
        <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
          <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
            <PieChart size={16} className="text-indigo-400"/> Tier Distribution
            <InfoTooltip text="Tokens are ranked into tiers based on momentum and risk. Tier A = immediate review (high momentum + low risk), Tier B = watch closely, Tier C = early signs needing confirmation, Excluded = high momentum but critical risk." />
          </h2>
          {pieData.length === 0 ? (
            <div className="flex items-center justify-center h-48 text-sm text-[#71717a]">No data yet</div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <RePie>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={90} paddingAngle={4} dataKey="value">
                  {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="transparent"/>)}
                </Pie>
                <Tooltip contentStyle={{ background: '#13131a', border: '1px solid #1e1e2e', borderRadius: 8, color: '#e4e4e7' }}/>
                <Legend wrapperStyle={{ color: '#71717a', fontSize: 12 }}/>
              </RePie>
            </ResponsiveContainer>
          )}
        </div>

        {/* Bar Chart — Momentum Scores (Best → Worst) */}
        <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
          <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
            <BarChart3 size={16} className="text-indigo-400"/> Momentum Scores
            <InfoTooltip text="Early Momentum Score combines attention, market flow, adoption, liquidity, smart money, narrative, and price compression into a single 0–100 rating. Higher = stronger early opportunity signal." />
          </h2>
          {barData.length === 0 ? (
            <div className="flex items-center justify-center h-48 text-sm text-[#71717a]">No data yet</div>
          ) : (
            <div className="overflow-y-auto" style={{ maxHeight: 400 }}>
              <ResponsiveContainer width="100%" height={Math.max(barData.length * 32, 280)}>
              <BarChart data={barData} layout="vertical" margin={{ top: 4, right: 30, left: 10, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" horizontal={false}/>
                <XAxis type="number" domain={[0, 100]} tick={{ fill: '#71717a', fontSize: 11 }} axisLine={false} tickLine={false} tickCount={5}/>
                <YAxis type="category" dataKey="name" tick={{ fill: '#e4e4e7', fontSize: 13, fontWeight: 700 }} axisLine={false} tickLine={false} width={55}/>
                <Tooltip cursor={{ fill: 'rgba(99,102,241,0.08)' }}
                  contentStyle={{ background: '#13131a', border: '1px solid #1e1e2e', borderRadius: 10, color: '#e4e4e7', fontSize: 13, fontWeight: 600 }}/>
                <Bar dataKey="score" radius={0} maxBarSize={24} barSize={18} fill="#6366f1">
                  {barData.length <= 15 && <LabelList dataKey="score" position="right" fill="#e4e4e7" fontSize={12} fontWeight={700}/>}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 p-1 rounded-xl bg-[#13131a] border border-[#1e1e2e]">
        {TABS.map(t=>(<button key={t.key} onClick={()=>setTab(t.key)} className={`flex-1 px-3 py-2.5 rounded-lg text-xs font-semibold transition-all ${tab===t.key?`${t.bg} ${t.color} ${t.border} border`:'text-[#71717a] border border-transparent'}`}><div>{t.label}</div><div className="text-[10px] opacity-60">{t.desc}</div></button>))}
      </div>

      {/* Token List */}
      {tokens.length === 0 ? (
        <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-12 text-center">
          <Wallet size={48} className="mx-auto mb-3 text-[#71717a]"/>
          <p className="text-lg font-medium text-[#e4e4e7]">No tokens in this tier</p>
          <p className="text-sm mt-1 text-[#71717a]">Run the pipeline from the Pipeline page to discover tokens</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">{tokens.map(t=><TokenRow key={t.id} token={t}/>)}</div>
      )}
    </div>
  );
}

function InfoTooltip({ text }: { text: string }) {
  const [show, setShow] = useState(false);
  return (
    <span className="relative inline-flex" onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      <Info size={13} className="text-[#71717a] hover:text-indigo-400 cursor-help transition-colors"/>
      {show && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 px-3 py-2 rounded-lg text-xs leading-relaxed bg-[#1e1e2e] border border-[#2e2e3e] text-[#e4e4e7] shadow-xl z-50 pointer-events-none">
          {text}
        </span>
      )}
    </span>
  );
}
