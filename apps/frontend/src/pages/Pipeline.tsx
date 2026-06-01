import { useEffect } from 'react';
import { Play, RefreshCw, CheckCircle, Clock, Zap, Activity, Loader2, Search, XCircle, Layers } from 'lucide-react';
import { usePipelineStatus, useTriggerPipeline } from '../hooks/useApi';

const LAYERS = [
  [1,'Discovery','7 sources scan'], [2,'Token Filtering','Identity + Safety + Manipulation'],
  [3,'Attention','Social velocity'], [4,'Market Flow','On-chain flow'], [5,'Adoption','Holder growth'],
  [6,'Liquidity Quality','Trading health'], [7,'Smart Money','Proven wallets'], [8,'Narrative','Sector context'],
  [9,'Price Compression','Entry timing'], [10,'Risk Score','Multi-dimension'], [11,'Early Momentum','Combined score'],
  [12,'Ranking','Tier A/B/C'],
];

// Friendly names for discovery sources
const SOURCE_NAMES: Record<string, string> = {
  dexscreener_volume: 'DEXScreener Volume',
  dexscreener_trending: 'DEXScreener Trending',
  twitter: 'Twitter/X',
  telegram: 'Telegram',
  reddit: 'Reddit',
  smart_wallet: 'Smart Wallet',
  dormant_awakening: 'Dormant Awakening',
  narrative: 'Narrative Discovery',
};

// Friendly names for Token Filtering sub-steps
const FILTERING_NAMES: Record<string, string> = {
  identity: 'Token Identity (dedup)',
  safety: 'Safety (honeypot / rug check)',
  manipulation: 'Manipulation (spam / fake activity)',
};

// Friendly names for Attention sub-steps
const ATTENTION_NAMES: Record<string, string> = {
  twitter: 'X (Twitter) Velocity',
  telegram: 'Telegram Velocity',
  reddit: 'Reddit Velocity',
  coingecko: 'Coingecko News',
};

// Static list — always visible under Discovery
const DISCOVERY_SOURCES = Object.keys(SOURCE_NAMES);
const FILTERING_STEPS = Object.keys(FILTERING_NAMES);
const ATTENTION_STEPS = Object.keys(ATTENTION_NAMES);

const STATS = [
  { icon: Clock, label: 'Last Run', color: 'text-indigo-400', bg: 'bg-indigo-500/10' },
  { icon: Search, label: 'Coins Discovered', color: 'text-green-500', bg: 'bg-green-500/10' },
  { icon: Zap, label: 'Status', color: 'text-yellow-500', bg: 'bg-yellow-500/10' },
  { icon: CheckCircle, label: 'Backend', color: 'text-green-500', bg: 'bg-green-500/10' },
];

export default function Pipeline() {
  const { data: status, refetch } = usePipelineStatus();
  const trigger = useTriggerPipeline();
  const progress = (status?.progress ?? {}) as NonNullable<typeof status>['progress'];
  const currentStep = progress?.step ?? 0;
  const pipelineStatus = progress?.status ?? 'idle';
  const isRunning = pipelineStatus === 'running';
  const isComplete = pipelineStatus === 'done' || pipelineStatus === 'completed';

  useEffect(() => {
    if (trigger.isSuccess) {
      refetch();
    }
  }, [trigger.isSuccess]);

  const totalFound = progress?.sub_layers
    ?.filter((s) => DISCOVERY_SOURCES.includes(s.name))
    .reduce((sum: number, s: { count: number }) => sum + s.count, 0) ?? 0;
  const lastRunTime = progress?.updated_at
    ? new Date(progress.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '—';

  const statValues = [
    lastRunTime,
    totalFound,
    isRunning ? `Step ${currentStep}/12` : isComplete ? 'Complete' : 'Ready',
    'Online',
  ];

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-3 text-[#e4e4e7]"><Activity size={24} className="text-indigo-400"/>Pipeline</h1>
          <p className="text-sm mt-1 text-[#71717a]">
            12-layer analysis · Auto-refreshes
            {isRunning && <span className="ml-2 text-indigo-400 flex items-center gap-1 inline-flex"><Loader2 size={12} className="animate-spin"/>Running...</span>}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={()=>refetch()} className="px-4 py-2 rounded-lg text-sm font-medium bg-[#13131a] border border-[#1e1e2e] text-[#71717a] hover:text-[#e4e4e7] flex items-center gap-2"><RefreshCw size={14}/>Refresh</button>
          <button onClick={()=>trigger.mutate()} disabled={isRunning} className="px-5 py-2 rounded-lg text-sm font-semibold bg-gradient-to-r from-indigo-500 to-purple-500 text-white flex items-center gap-2 shadow-lg shadow-indigo-500/20 disabled:opacity-60 transition-all">
            {isRunning ? <Loader2 size={14} className="animate-spin"/> : <Play size={14} fill="white"/>}
            {isRunning ? 'Pipeline Running...' : 'Run Full Pipeline'}
          </button>
        </div>
      </div>

      {isRunning && (
        <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-xl p-4 mb-6">
          <div className="flex items-center gap-3">
            <Loader2 size={20} className="animate-spin text-indigo-400"/>
            <div className="flex-1">
              <div className="text-sm font-semibold text-indigo-400">
                Step {currentStep}/12: {progress?.layer ?? '...'}
              </div>
              <div className="text-xs text-[#71717a] mt-0.5">{progress?.detail || 'Processing...'}</div>
            </div>
            <div className="text-xs text-[#71717a]">{(currentStep/12*100).toFixed(0)}%</div>
          </div>
          <div className="h-1.5 rounded-full bg-[#1e1e2e] mt-3 overflow-hidden">
            <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500" style={{ width: `${(currentStep/12)*100}%` }}/>
          </div>
        </div>
      )}

      {isComplete && (
        <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-4 mb-6">
          <div className="flex items-center gap-3">
            <CheckCircle size={20} className="text-green-400"/>
            <div className="flex-1">
              <div className="text-sm font-semibold text-green-400">Pipeline Complete</div>
              <div className="text-xs text-[#71717a] mt-0.5">{progress?.detail || 'All 12 layers finished.'}</div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        {STATS.map((s, i) => (
          <div key={s.label} className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-4 flex items-center gap-3">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${s.bg}`}><s.icon size={18} className={s.color}/></div>
            <div><div className="text-xs text-[#71717a]">{s.label}</div><div className="text-lg font-bold text-[#e4e4e7]">{statValues[i]}</div></div>
          </div>
        ))}
      </div>

      <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]"><Layers size={16}/>Pipeline Layers</h2>
      <div className="space-y-1">
        {LAYERS.map(([num, name, desc]) => {
          const n = num as number;
          const isDone = isComplete || currentStep > n;
          const isCurrent = !isComplete && currentStep === n;
          const subLayers = progress?.sub_layers;
          const runMap = new Map<string, { count: number; status: string }>();
          if (subLayers) {
            for (const sl of subLayers) {
              runMap.set(sl.name, sl);
            }
          }

          // Determine sub-items for this layer
          let subKeys: string[] = [];
          let subNames: Record<string, string> = {};
          let subLabel = '';
          if (n === 1) { subKeys = DISCOVERY_SOURCES; subNames = SOURCE_NAMES; subLabel = 'found'; }
          if (n === 2) { subKeys = FILTERING_STEPS; subNames = FILTERING_NAMES; subLabel = 'passed'; }
          if (n === 3) { subKeys = ATTENTION_STEPS; subNames = ATTENTION_NAMES; subLabel = 'tracked'; }
          const showSubs = subKeys.length > 0;
          const totalSub = subKeys.reduce((sum, k) => sum + (runMap.get(k)?.count ?? 0), 0);

          return (
            <div key={n}>
              <div className={`bg-[#13131a] border rounded-xl p-4 flex items-center gap-4 transition-all ${
                isCurrent ? 'border-indigo-500/50 shadow-lg shadow-indigo-500/10' : isDone ? 'border-green-500/20' : 'border-[#1e1e2e]'
              }`}>
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 ${
                  isCurrent ? 'bg-gradient-to-br from-indigo-500 to-purple-500 text-white animate-pulse' :
                  isDone ? 'bg-green-500/20 text-green-500' :
                  'bg-[#1e1e2e] text-[#71717a]'
                }`}>
                  {isDone ? <CheckCircle size={14}/> : isCurrent ? <Loader2 size={14} className="animate-spin"/> : n}
                </div>
                <div className="flex-1">
                  <div className={`text-sm font-semibold ${isCurrent ? 'text-indigo-400' : isDone ? 'text-green-500' : 'text-[#71717a]'}`}>
                    {name as string}
                    {showSubs && isDone && totalSub > 0 && (
                      <span className="ml-2 text-xs text-green-400">({totalSub} {subLabel})</span>
                    )}
                  </div>
                  <div className="text-xs text-[#71717a]">{desc as string}</div>
                </div>
                <div className="flex items-center gap-1 text-xs">
                  {isCurrent ? (
                    <span className="text-indigo-400 flex items-center gap-1"><Loader2 size={10} className="animate-spin"/>Running</span>
                  ) : isDone ? (
                    <span className="text-green-500 flex items-center gap-1"><CheckCircle size={10}/>Done</span>
                  ) : (
                    <span className="text-[#71717a] flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-[#1e1e2e]"/>Pending</span>
                  )}
                </div>
              </div>

              {/* Sub-layers: always show, with counts when available */}
              {showSubs && (
                <div className="ml-8 mt-0.5 space-y-0.5 border-l border-[#1e1e2e] pl-4">
                  {subKeys.map((key) => {
                    const run = runMap.get(key);
                    const hasRun = !!run;
                    const done = hasRun && run.status === 'done';
                    const failed = hasRun && run.status === 'failed';
                    return (
                      <div key={key} className="flex items-center gap-3 py-1.5 px-3 rounded-lg bg-[#0a0a10]/50">
                        {isCurrent ? (
                          <Loader2 size={12} className="text-indigo-400 animate-spin"/>
                        ) : done ? (
                          <Search size={12} className="text-green-500"/>
                        ) : failed ? (
                          <XCircle size={12} className="text-red-500"/>
                        ) : (
                          <div className="w-3 h-3 rounded-full border border-[#1e1e2e]"/>
                        )}
                        <span className="text-xs text-[#a1a1aa] flex-1">
                          {subNames[key] || key}
                        </span>
                        {isCurrent ? (
                          <span className="text-xs text-indigo-400">processing…</span>
                        ) : done ? (
                          <span className="text-xs text-green-500 font-mono">{run.count} {subLabel}</span>
                        ) : failed ? (
                          <span className="text-xs text-red-500">failed</span>
                        ) : (
                          <span className="text-xs text-[#52525b]">—</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
