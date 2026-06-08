import { useState, useEffect, useRef } from 'react';
import { flushSync } from 'react-dom';
import { Play, RefreshCw, CheckCircle, Loader2, Activity, Layers, TrendingUp, Users, BarChart3, ExternalLink, ChevronDown, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { usePipelineStatus, usePipelineResults, useTriggerPipeline } from '../hooks/useApi';
import { api } from '../api/client';
import type { UnifiedTokenData, UnifiedWindowData } from '../api/client';

const STEPS = [
  { key: 'telegram', label: 'Telegram Scan', desc: 'Scan groups for token mentions' },
  { key: 'dexscreener', label: 'DexScreener + GMGN', desc: 'Parallel enrich: price/volume + GMGN metrics' },
  { key: 'dedup', label: 'Deduplication', desc: 'Merge duplicate tokens' },
  { key: 'aggregate', label: 'Windowed Agg', desc: 'Compute 5m/1h/6h/24h buckets' },
  { key: 'persist', label: 'Persist', desc: 'Save to database' },
];

const WINDOWS = ['5m', '1h', '6h', '24h'] as const;

function formatCompact(n: number | undefined | null): string {
  if (n == null) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(2) + 'K';
  if (n < 0.0001 && n > 0) return n.toExponential(2);
  return n.toFixed(n >= 1 ? 2 : 6);
}

export default function Pipeline() {
  const qc = useQueryClient();
  const { data: status, isFetching: statusFetching } = usePipelineStatus();
  const { data: results, isFetching: resultsFetching } = usePipelineResults({ limit: 500 });
  const trigger = useTriggerPipeline();

  const [runWindow, setRunWindow] = useState<string>('24h');
  const [displayWindow, setDisplayWindow] = useState<string>('24h');
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [sortField, setSortField] = useState<string>('rank');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 50;
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    if (dropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [dropdownOpen]);

  const isRunning = status?.status === 'running';
  const isDone = status?.status === 'done';
  const isError = status?.status === 'error';
  const currentStep = STEPS.findIndex(s => s.key === status?.step) ?? -1;

  const handleRefresh = async () => {
    flushSync(() => setRefreshing(true));
    await api.clearPipelineResults();
    qc.resetQueries({ queryKey: ['pipeline-status'] });
    qc.resetQueries({ queryKey: ['pipeline-results'] });
    setTimeout(() => setRefreshing(false), 1200);
  };

  const refetchData = () => {
    qc.invalidateQueries({ queryKey: ['pipeline-status'] });
    qc.invalidateQueries({ queryKey: ['pipeline-results'] });
  };

  const handleRun = async () => {
    trigger.mutate(runWindow);

    // Poll pipeline status until done, then refresh
    const poll = async () => {
      for (let i = 0; i < 120; i++) {  // max 4 minutes
        await new Promise(r => setTimeout(r, 3000));  // every 3s
        try {
          const s = await api.getPipelineStatus();
          if (s.status === 'done') {
            refetchData();
            return;
          }
          if (s.status === 'error') {
            refetchData();
            return;
          }
        } catch {
          // API not ready yet, keep polling
        }
      }
      refetchData();  // timeout — refetch anyway
    };
    poll();
  };

  const isRefreshing = refreshing || statusFetching || resultsFetching;
  const hasData = results && results.tokens && results.tokens.length > 0;

  const tokens = results?.tokens ?? [];
  const totalTokens = results?.total ?? 0;

  const handleSort = (field: string) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('desc');
    }
    setPage(0);
  };

  const sortIcon = (field: string) => {
    if (sortField !== field) return <ArrowUpDown size={12} className="inline ml-1 opacity-30" />;
    return sortDir === 'asc'
      ? <ArrowUp size={12} className="inline ml-1 text-indigo-400" />
      : <ArrowDown size={12} className="inline ml-1 text-indigo-400" />;
  };

  const displayTokens = [...tokens]
    .sort((a, b) => {
      const wA = (a.windows[displayWindow as keyof typeof a.windows] ?? {}) as UnifiedWindowData;
      const wB = (b.windows[displayWindow as keyof typeof b.windows] ?? {}) as UnifiedWindowData;
      const tgA = wA.telegram ?? { mentions: 0, replies: 0, users: 0, reactions: 0 };
      const tgB = wB.telegram ?? { mentions: 0, replies: 0, users: 0, reactions: 0 };

      let valA: number = 0, valB: number = 0;
      switch (sortField) {
        case 'rank': valA = a.rank; valB = b.rank; break;
        case 'symbol': return sortDir === 'asc'
          ? (a.symbol || '').localeCompare(b.symbol || '')
          : (b.symbol || '').localeCompare(a.symbol || '');
        case 'price': valA = wA.price ?? 0; valB = wB.price ?? 0; break;
        case 'volume': valA = wA.volume ?? 0; valB = wB.volume ?? 0; break;
        case 'trades': valA = wA.trades ?? 0; valB = wB.trades ?? 0; break;
        case 'liquidity': valA = wA.liquidity ?? 0; valB = wB.liquidity ?? 0; break;
        case 'mcap': valA = wA.market_cap ?? 0; valB = wB.market_cap ?? 0; break;
        case 'tg': valA = tgA.mentions; valB = tgB.mentions; break;
        case 'tg_replies': valA = tgA.replies ?? 0; valB = tgB.replies ?? 0; break;
        case 'tg_users': valA = tgA.users ?? 0; valB = tgB.users ?? 0; break;
        case 'tg_reactions': valA = tgA.reactions ?? 0; valB = tgB.reactions ?? 0; break;
        case 'tg_groups': valA = tgA.groups ?? 0; valB = tgB.groups ?? 0; break;
        default: valA = a.rank; valB = b.rank;
      }
      return sortDir === 'asc' ? valA - valB : valB - valA;
    });

  const totalPages = Math.ceil(displayTokens.length / PAGE_SIZE);
  const pagedTokens = displayTokens.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-3 text-[#e4e4e7]">
            <Activity size={24} className="text-indigo-400" />
              Pipeline
          </h1>
          <p className="text-sm mt-1 text-[#71717a]">
            Telegram → DexScreener → GMGN → Dedup → Persist
            {isRunning && (
              <span className="ml-2 text-indigo-400 inline-flex items-center gap-1">
                <Loader2 size={12} className="animate-spin" />Running...
              </span>
            )}
            {isDone && (
              <span className="ml-2 text-green-400 inline-flex items-center gap-1">
                <CheckCircle size={12} />Complete · {totalTokens} tokens
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleRefresh}
            className="px-3 py-2 rounded-lg text-sm font-medium bg-[#13131a] border border-[#1e1e2e] text-[#71717a] hover:text-[#e4e4e7] flex items-center gap-1.5 disabled:opacity-50"
            title="Refresh"
            disabled={isRefreshing}>
            <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
          </button>

          {/* Split button: Run + dropdown */}
          <div className="relative" ref={dropdownRef}>
            <div className="flex">
              <button onClick={handleRun} disabled={isRunning}
                className="px-5 py-2 rounded-l-lg text-sm font-semibold bg-gradient-to-r from-indigo-500 to-purple-500 text-white flex items-center gap-2 shadow-lg shadow-indigo-500/20 disabled:opacity-60 transition-all">
                {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} fill="white" />}
                {isRunning ? 'Running...' : `Run (${runWindow})`}
              </button>
              <button
                onClick={() => setDropdownOpen(!dropdownOpen)}
                disabled={isRunning}
                className="px-2 py-2 rounded-r-lg bg-gradient-to-r from-indigo-500 to-purple-500 text-white border-l border-white/20 flex items-center shadow-lg shadow-indigo-500/20 disabled:opacity-60 transition-all"
              >
                <ChevronDown size={14} className={`transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} />
              </button>
            </div>
            {dropdownOpen && (
              <div className="absolute right-0 mt-2 w-32 bg-[#18181b] border border-[#27272a] rounded-lg shadow-xl z-50 overflow-hidden">
                {WINDOWS.map(w => (
                  <button
                    key={w}
                    onClick={() => { setRunWindow(w); setDropdownOpen(false); }}
                    className={`w-full text-left px-4 py-2.5 text-sm font-medium transition-colors flex items-center justify-between ${
                      runWindow === w
                        ? 'bg-indigo-500/10 text-indigo-400'
                        : 'text-[#a1a1aa] hover:bg-[#27272a] hover:text-[#e4e4e7]'
                    }`}
                  >
                    {w}
                    {runWindow === w && <span className="text-indigo-400 text-xs">✓</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {isError && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-6">
          <p className="text-sm text-red-400 whitespace-pre-wrap line-clamp-4">{status?.detail}</p>
        </div>
      )}

      {isRunning && (
        <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-xl p-4 mb-6">
          <div className="flex items-center gap-3 mb-3">
            <Loader2 size={20} className="animate-spin text-indigo-400" />
            <div className="flex-1">
              <div className="text-sm font-semibold text-indigo-400">
                {status?.step ? STEPS.find(s => s.key === status.step)?.label ?? status.step : 'Starting...'}
              </div>
              <div className="text-xs text-[#71717a] mt-0.5">{status?.detail}</div>
            </div>
            <div className="text-right">
              <div className="text-sm font-bold text-[#e4e4e7]">
                {status?.tokens ?? 0}{status?.total ? ` / ${status.total}` : ''}
              </div>
              <div className="text-[10px] text-[#52525b]">tokens</div>
            </div>
          </div>
          {/* Progress bar */}
          {status?.total ? (
            <div className="w-full h-1.5 bg-[#1e1e2e] rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500"
                style={{ width: `${Math.min(100, ((status.tokens || 0) / status.total) * 100)}%` }}
              />
            </div>
          ) : null}
          <div className="flex gap-1.5 mt-3">
            {STEPS.map((s, i) => {
              const done = currentStep > i;
              const active = currentStep === i;
              return (
                <div key={s.key}
                  className={`flex-1 h-1.5 rounded-full transition-all ${
                    done ? 'bg-green-500' : active ? 'bg-indigo-500 animate-pulse' : 'bg-[#1e1e2e]'
                  }`}
                  title={s.label} />
              );
            })}
          </div>
        </div>
      )}

      {/* Full-page loading overlay while refreshing */}
      {refreshing ? (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <Loader2 size={36} className="animate-spin text-indigo-400" />
          <p className="text-sm text-[#71717a]">Refreshing pipeline data...</p>
        </div>
      ) : (
        <div>
          <div className="grid grid-cols-3 gap-3 mb-6">
            {[
              { icon: TrendingUp, color: 'indigo', label: 'Total Tokens Found', value: isRefreshing ? '—' : totalTokens },
              { icon: BarChart3, color: 'purple', label: 'Total Volume', value: isRefreshing ? '—' : formatCompact(tokens.reduce((sum, t) => sum + (t.windows[displayWindow as keyof typeof t.windows]?.volume ?? 0), 0)) },
              { icon: Users, color: 'green', label: 'Total Trades', value: isRefreshing ? '—' : tokens.reduce((sum, t) => sum + (t.windows[displayWindow as keyof typeof t.windows]?.trades ?? 0), 0) },
            ].map((s) => (
              <div key={s.label} className={`bg-[#13131a] border border-[#1e1e2e] rounded-xl p-4 flex items-center gap-3 ${isRefreshing ? 'opacity-40' : ''}`}>
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                  s.color === 'indigo' ? 'bg-indigo-500/10' : s.color === 'purple' ? 'bg-purple-500/10' : 'bg-green-500/10'
                }`}>
                  <s.icon size={20} className={
                    s.color === 'indigo' ? 'text-indigo-400' : s.color === 'purple' ? 'text-purple-400' : 'text-green-400'
                  } />
                </div>
                <div>
                  <div className="text-xs text-[#71717a]">{s.label}</div>
                  <div className="text-lg font-bold text-[#e4e4e7]">{s.value}</div>
                </div>
              </div>
            ))}
          </div>

      <h2 className="text-sm font-semibold mb-3 flex items-center gap-2 text-[#e4e4e7]">
        <Layers size={16} />Pipeline Steps
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 mb-8">
        {STEPS.map((s, i) => {
          const done = isDone || (isRunning && currentStep > i);
          const active = isRunning && currentStep === i;
          return (
            <div key={s.key}
              className={`rounded-xl p-3 border text-center transition-all ${
                done ? 'border-green-500/30 bg-green-500/5' :
                active ? 'border-indigo-500/50 bg-indigo-500/10' :
                'border-[#1e1e2e] bg-[#13131a]'
              }`}>
              <div className={`text-lg mb-1 ${
                done ? 'text-green-400' : active ? 'text-indigo-400' : 'text-[#52525b]'
              }`}>
                {done ? <CheckCircle size={18} className="mx-auto" /> :
                 active ? <Loader2 size={18} className="mx-auto animate-spin" /> :
                 <span className="text-xs">{i + 1}</span>}
              </div>
              <div className={`text-xs font-semibold ${done ? 'text-green-400' : active ? 'text-indigo-400' : 'text-[#71717a]'}`}>
                {s.label}
              </div>
              <div className="text-[10px] text-[#52525b] mt-0.5">{s.desc}</div>
            </div>
          );
        })}
      </div>

      {tokens.length > 0 && (
        <>
          <div className="flex items-center gap-2 mb-4">
            <span className="text-sm text-[#71717a]">Time window:</span>
            {WINDOWS.map(w => (
              <button key={w} onClick={() => setDisplayWindow(w)}
                className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                  displayWindow === w
                    ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30'
                    : 'bg-[#13131a] border border-[#1e1e2e] text-[#71717a] hover:text-[#e4e4e7]'
                }`}>
                {w}
              </button>
            ))}
          </div>

          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#1e1e2e] text-[10px] text-[#52525b] uppercase tracking-wider">
                    <th className="text-left px-4 py-1" rowSpan={2}>#</th>
                    <th className="text-left px-4 py-1" rowSpan={2}>Token</th>
                    <th className="text-right px-4 py-1" rowSpan={2}>Price</th>
                    <th className="text-right px-4 py-1" rowSpan={2}>Volume</th>
                    <th className="text-right px-4 py-1" rowSpan={2}>Trades</th>
                    <th className="text-right px-4 py-1" rowSpan={2}>Liq</th>
                    <th className="text-right px-4 py-1" rowSpan={2}>MCap</th>
                    <th className="text-center px-1 py-1 border-b border-[#27272a]" colSpan={5}>TG</th>
                  </tr>
                  <tr className="border-b border-[#1e1e2e] text-[11px] text-[#52525b]">
                    <th className="text-right px-2 py-1 cursor-pointer hover:text-[#e4e4e7] select-none" onClick={() => handleSort('tg')}>
                      Msg{sortIcon('tg')}
                    </th>
                    <th className="text-right px-2 py-1 cursor-pointer hover:text-[#e4e4e7] select-none" onClick={() => handleSort('tg_replies')}>
                      💬{sortIcon('tg_replies')}
                    </th>
                    <th className="text-right px-2 py-1 cursor-pointer hover:text-[#e4e4e7] select-none" onClick={() => handleSort('tg_users')}>
                      👤{sortIcon('tg_users')}
                    </th>
                    <th className="text-right px-2 py-1 cursor-pointer hover:text-[#e4e4e7] select-none" onClick={() => handleSort('tg_reactions')}>
                      👍{sortIcon('tg_reactions')}
                    </th>
                    <th className="text-right px-2 py-1 cursor-pointer hover:text-[#e4e4e7] select-none" onClick={() => handleSort('tg_groups')}>
                      Grp{sortIcon('tg_groups')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {pagedTokens.map((token: UnifiedTokenData) => {
                    const w = (token.windows[displayWindow as keyof typeof token.windows] ?? {}) as UnifiedWindowData;
                    const tg = w.telegram ?? { mentions: 0, users: 0, groups: 0, replies: 0, reactions: 0 };
                    return (
                      <tr key={`${token.chain}:${token.token_address}`}
                        className="border-b border-[#1e1e2e] hover:bg-[#1a1a24] transition-colors">
                        <td className="px-4 py-3">
                          <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                            token.rank <= 3 ? 'bg-yellow-500/20 text-yellow-400' :
                            token.rank <= 10 ? 'bg-indigo-500/20 text-indigo-400' :
                            'text-[#71717a]'
                          }`}>{token.rank}</span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="font-semibold text-[#e4e4e7]">
                            {token.symbol || token.token_address.slice(0, 8)}
                          </div>
                          <div className="text-xs text-[#52525b]">
                            {token.chain}
                            {token.dex_url && (
                              <a href={token.dex_url} target="_blank" rel="noopener noreferrer" className="ml-1 inline-flex text-indigo-400 hover:text-indigo-300">
                                <ExternalLink size={10} />
                              </a>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-[#e4e4e7]">${formatCompact(w.price)}</td>
                        <td className="px-4 py-3 text-right font-mono text-[#e4e4e7]">${formatCompact(w.volume)}</td>
                        <td className="px-4 py-3 text-right font-mono text-[#71717a]">{formatCompact(w.trades)}</td>
                        <td className="px-4 py-3 text-right font-mono text-[#71717a]">${formatCompact(w.liquidity)}</td>
                        <td className="px-4 py-3 text-right font-mono text-[#71717a]">${formatCompact(w.market_cap)}</td>
                        <td className="px-2 py-3 text-right font-mono text-[#e4e4e7] tabular-nums">{tg.mentions}</td>
                        <td className="px-2 py-3 text-right font-mono text-[#71717a] tabular-nums">{tg.replies ?? 0}</td>
                        <td className="px-2 py-3 text-right font-mono text-[#71717a] tabular-nums">{tg.users ?? 0}</td>
                        <td className="px-2 py-3 text-right font-mono text-[#71717a] tabular-nums">{tg.reactions ?? 0}</td>
                        <td className="px-2 py-3 text-right font-mono tabular-nums">
                          <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                            (tg.groups ?? 0) >= 5 ? 'bg-green-500/20 text-green-400' :
                            (tg.groups ?? 0) >= 2 ? 'bg-indigo-500/20 text-indigo-400' :
                            'text-[#71717a]'
                          }`}>{tg.groups ?? 0}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="flex items-center justify-between mt-3 text-xs text-[#52525b]">
            <span>
              Showing {pagedTokens.length > 0 ? page * PAGE_SIZE + 1 : 0}–{Math.min((page + 1) * PAGE_SIZE, displayTokens.length)} of {displayTokens.length} tokens
              {displayTokens.length < totalTokens && ` (${totalTokens} total in DB)`}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage(0)}
                disabled={page === 0}
                className="px-2 py-1 rounded bg-[#1e1e2e] hover:bg-[#27272a] disabled:opacity-30 disabled:cursor-not-allowed"
              >««</button>
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-2 py-1 rounded bg-[#1e1e2e] hover:bg-[#27272a] disabled:opacity-30 disabled:cursor-not-allowed"
              >«</button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 7) {
                  pageNum = i;
                } else if (page < 3) {
                  pageNum = i;
                } else if (page > totalPages - 4) {
                  pageNum = totalPages - 7 + i;
                } else {
                  pageNum = page - 3 + i;
                }
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    className={`px-2 py-1 rounded ${
                      pageNum === page
                        ? 'bg-indigo-500/20 text-indigo-400'
                        : 'bg-[#1e1e2e] hover:bg-[#27272a]'
                    }`}
                  >{pageNum + 1}</button>
                );
              })}
              <button
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="px-2 py-1 rounded bg-[#1e1e2e] hover:bg-[#27272a] disabled:opacity-30 disabled:cursor-not-allowed"
              >»</button>
              <button
                onClick={() => setPage(totalPages - 1)}
                disabled={page >= totalPages - 1}
                className="px-2 py-1 rounded bg-[#1e1e2e] hover:bg-[#27272a] disabled:opacity-30 disabled:cursor-not-allowed"
              >»»</button>
            </div>
          </div>
        </>
      )}

      {!isRunning && tokens.length === 0 && !isError && (
        <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-12 text-center">
          <div className="w-16 h-16 rounded-full bg-indigo-500/10 flex items-center justify-center mx-auto mb-4">
            <Play size={24} className="text-indigo-400" />
          </div>
          <h3 className="text-lg font-semibold text-[#e4e4e7] mb-2">No Pipeline Data Yet</h3>
          <p className="text-sm text-[#71717a] mb-4 max-w-md mx-auto">
            Run the unified pipeline to scan Telegram groups, enrich tokens via DexScreener & GMGN, and rank them.
          </p>
          <button onClick={handleRun}
            className="px-5 py-2 rounded-lg text-sm font-semibold bg-gradient-to-r from-indigo-500 to-purple-500 text-white shadow-lg shadow-indigo-500/20">
            Run Pipeline
          </button>
        </div>
      )}
        </div>
      )}
    </div>
  );
}
