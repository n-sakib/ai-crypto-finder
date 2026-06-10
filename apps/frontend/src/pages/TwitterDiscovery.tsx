import React, { useState, useEffect, useRef } from 'react';
import { Search, Hash, TrendingUp, RefreshCw, ExternalLink, Layers, AlertCircle, Settings, Play, Plus, X, Power, Users, Award, AlertTriangle } from 'lucide-react';
import { useTwitterDiscovery, useTwitterSources, useTwitterStats } from '../hooks/useApi';
import { twitterApi } from '../api/client';

const SOURCE_TYPE_LABELS: Record<string, string> = {
  cashtag_search: 'Cashtag',
  keyword_search: 'Keyword',
  address_search: 'Address',
  account_monitor: 'Account',
};

const SOURCE_TYPE_COLORS: Record<string, string> = {
  cashtag_search: 'bg-green-500/10 text-green-400 border-green-500/20',
  keyword_search: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  address_search: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  account_monitor: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
};

const CHAIN_COLORS: Record<string, string> = {
  ethereum: 'bg-blue-500/15 text-blue-400',
  solana: 'bg-gradient-to-r from-purple-500/15 to-cyan-500/15 text-purple-400',
  bsc: 'bg-yellow-500/15 text-yellow-400',
  base: 'bg-blue-600/15 text-blue-300',
};

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + '\u2026' : s;
}

function loadSettings(): Partial<{ window: string; limit: number; min_mentions: number; min_users: number }> {
  try {
    const raw = localStorage.getItem('twitter_discovery_settings');
    if (raw) return JSON.parse(raw);
  } catch {}
  return {};
}

function saveSettings(s: Record<string, unknown>) {
  localStorage.setItem('twitter_discovery_settings', JSON.stringify(s));
}

export default function TwitterDiscovery() {
  const [settings, setSettings] = useState<{ window: string; limit: number; min_mentions: number; min_users: number }>(() => ({
    window: '24h',
    limit: 50,
    min_mentions: 1,
    min_users: 1,
    ...loadSettings(),
  }));
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  const { data: discovery, isLoading: discLoading, refetch: refetchDiscovery } = useTwitterDiscovery({
    window: settings.window,
    limit: settings.limit,
    min_mentions: settings.min_mentions,
    min_users: settings.min_users,
  });
  const { data: sources, isLoading: srcLoading, refetch: refetchSources } = useTwitterSources();
  const { data: stats, refetch: refetchStats } = useTwitterStats();
  const [expandedToken, setExpandedToken] = useState<number | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [newQuery, setNewQuery] = useState('');
  const [adding, setAdding] = useState(false);
  const [statusConfigured, setStatusConfigured] = useState<boolean | null>(null);
  const [statusMessage, setStatusMessage] = useState('');
  const [collectError, setCollectError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Check if Twitter credentials are configured
  useEffect(() => {
    twitterApi.getStatus().then(s => {
      setStatusConfigured(s.configured);
      setStatusMessage(s.message);
    }).catch(() => setStatusConfigured(false));
  }, []);

  const handleAddSource = async () => {
    const q = newQuery.trim();
    if (!q || adding) return;
    setAdding(true);
    try {
      const st = q.startsWith('@') ? 'account_monitor' : q.startsWith('0x') ? 'address_search' : 'keyword_search';
      const displayName = q.startsWith('@') ? q : q;
      await twitterApi.addSource(q, displayName, st);
      setNewQuery('');
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to add source', e);
    }
    setAdding(false);
  };

  const handleRemove = async (sourceId: string) => {
    try {
      await twitterApi.removeSource(sourceId);
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to remove source', e);
    }
  };

  const handleToggle = async (sourceId: string) => {
    try {
      await twitterApi.toggleSource(sourceId);
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to toggle source', e);
    }
  };

  const [progress, setProgress] = useState<{
    status: string; candidates_found?: number; tweets_stored?: number;
    mentions_stored?: number; tokens_discovered?: number;
    sources_done?: number; sources_total?: number; query?: string;
  } | null>(null);

  const handleCollect = async () => {
    setCollecting(true);
    setCollectError(null);
    setProgress({
      status: 'starting',
      sources_done: 0,
      sources_total: sources?.filter(s => s.enabled).length || 15,
    });

    try {
      const res = await fetch(`/api/v1/twitter/collect?window=${settings.window}`, { method: 'POST' });
      const reader = res.body?.getReader();
      if (!reader) { setCollecting(false); return; }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = '';
        let currentEvent = '';
        let currentData = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7);
          } else if (line.startsWith('data: ')) {
            currentData = line.slice(6);
          } else if (line === '' && currentData) {
            try {
              const d = JSON.parse(currentData);
              if (currentEvent === 'progress' || currentEvent === 'done') {
                setProgress(d);
              }
              if (currentEvent === 'done') {
                setCollecting(false);
                setProgress(null);
                refetchDiscovery();
                refetchSources();
                refetchStats();
                return;
              }
              if (currentEvent === 'error') {
                setCollectError(d.error || 'Collection failed');
                setCollecting(false);
                setProgress(prev => prev ? { ...prev, status: 'error' } : null);
                refetchDiscovery();
                refetchSources();
                refetchStats();
                return;
              }
            } catch {}
            currentEvent = '';
            currentData = '';
          }
        }
        buffer = lines[lines.length - 1] || '';
      }
      setCollecting(false);
      setProgress(null);
      refetchDiscovery();
      refetchSources();
      refetchStats();
    } catch (e: any) {
      setCollectError(String(e?.message || e));
      setCollecting(false);
      setProgress(null);
    }
  };

  const enabledSources = sources?.filter(s => s.enabled) ?? [];
  const disabledSources = sources?.filter(s => !s.enabled) ?? [];

  const lastDiscoveryLabel = stats?.latest_mention_at
    ? new Date(stats.latest_mention_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className="px-2 py-3 space-y-4">
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-bold text-[#e4e4e7] flex items-center gap-2">
            <TrendingUp size={24} className="text-blue-400" />
            Twitter/X Discovery
          </h1>
          <p className="text-sm mt-1 text-[#71717a]">
            {stats?.enabled_sources ?? 0} queries · {stats?.candidate_tokens ?? 0} tokens · {stats?.total_mentions ?? 0} mentions
          </p>
        </div>
        <button
          onClick={handleCollect}
          disabled={collecting || statusConfigured === false}
          title={statusConfigured === false ? statusMessage : 'Run Twitter discovery'}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          {collecting ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
          {collecting ? 'Running\u2026' : 'Run Discovery'}
        </button>
      </div>

      {/* ── Configuration Warning ────────────────────────────── */}
      {statusConfigured === false && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-red-500/10 border border-red-500/20">
          <AlertTriangle size={18} className="text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-red-400 font-medium">Twitter Not Configured</p>
            <p className="text-xs text-red-300/70 mt-1">
              Set <code className="text-xs bg-red-500/10 px-1 py-0.5 rounded">TWITTER_USERNAME</code> and{' '}
              <code className="text-xs bg-red-500/10 px-1 py-0.5 rounded">TWITTER_PASSWORD</code> in{' '}
              <code className="text-xs bg-red-500/10 px-1 py-0.5 rounded">apps/backend/.env</code> to enable Twitter/X discovery.
            </p>
          </div>
        </div>
      )}

      {/* ── Error Banner ──────────────────────────────────────── */}
      {collectError && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-red-500/10 border border-red-500/20">
          <AlertTriangle size={18} className="text-red-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-red-400 font-medium">Collection Error</p>
            <p className="text-xs text-red-300/70 mt-0.5 break-all">{collectError}</p>
          </div>
          <button onClick={() => setCollectError(null)} className="text-red-400 hover:text-red-300">
            <X size={14} />
          </button>
        </div>
      )}

      {/* ── Stats Cards ──────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Search} label="Queries" value={enabledSources.length}
          color="text-orange-400" bg="bg-orange-500/10" loading={collecting}
          sub={lastDiscoveryLabel ? `Last: ${lastDiscoveryLabel}` : undefined} />
        <StatCard icon={TrendingUp} label="Tokens" value={discovery?.total_tokens ?? 0}
          color="text-green-400" bg="bg-green-500/10" loading={collecting || discLoading} />
        <StatCard icon={Hash} label="Mentions" value={discovery?.tokens?.reduce((s, t) => s + t.mention_count, 0) ?? 0}
          color="text-yellow-400" bg="bg-yellow-500/10" loading={collecting || discLoading} />
        <StatCard icon={Award} label="Authority" value={discovery?.tokens?.reduce((s, t) => s + t.authority_mentions, 0) ?? 0}
          color="text-purple-400" bg="bg-purple-500/10" loading={collecting || discLoading} />
      </div>

      {/* ── Progress Bar ──────────────────────────────────────── */}
      {collecting && progress && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-[#a1a1aa]">
              {progress.status === 'starting' ? 'Initializing\u2026' :
               progress.status === 'searching' && progress.query ? `Searching: "${truncate(progress.query, 40)}" (${(progress.sources_done ?? 0)}/${progress.sources_total ?? '?'})\u2026` :
               progress.status === 'searching' ? `Searching Twitter (${(progress.sources_done ?? 0)}/${progress.sources_total ?? '?'})\u2026` :
               progress.status === 'extracting' ? `Extracting tokens (${progress.candidates_found ?? 0} candidates)\u2026` :
               progress.status === 'storing' ? `Storing results\u2026` :
               progress.status === 'done' ? `Done: ${progress.tokens_discovered ?? 0} tokens, ${progress.mentions_stored ?? 0} mentions` :
               progress.status === 'error' ? 'Error' :
               'Working\u2026'}
            </span>
            {progress.sources_total && progress.sources_total > 0 ? (
              <span className="text-xs text-blue-400 font-mono">
                {Math.round(((progress.sources_done ?? 0) / progress.sources_total) * 100)}%
              </span>
            ) : (
              <span className="text-xs text-blue-400 font-mono animate-pulse">
                {progress.status === 'searching' ? '...' : ''}
              </span>
            )}
          </div>
          <div className="w-full bg-[#1a1a24] rounded-full h-2 border border-[#1e1e2e]">
            <div
              className="bg-blue-500 h-full rounded-full transition-all duration-500 ease-out"
              style={{
                width: progress.status === 'done' ? '100%' :
                       progress.status === 'error' ? '100%' :
                       progress.sources_total && progress.sources_total > 0
                         ? `${Math.round(((progress.sources_done ?? 0) / progress.sources_total) * 100)}%`
                         : progress.status === 'extracting' ? '70%' :
                           progress.status === 'storing' ? '90%' : '10%'
              }}
            />
          </div>
        </div>
      )}

      {/* ── Settings Bar ──────────────────────────────────────── */}
      <div className="mb-4">
        <button onClick={() => setShowSettings(!showSettings)} className="flex items-center gap-1.5 text-xs text-[#71717a] hover:text-[#a1a1aa] transition-colors">
          <Settings size={12} />
          {showSettings ? 'Hide' : 'Filters'}: window={settings.window} · min mentions={settings.min_mentions} · min users={settings.min_users} · limit={settings.limit}
        </button>
        {showSettings && (
          <div className="mt-2 p-3 rounded-lg bg-[#13131a] border border-[#1e1e2e] flex flex-wrap gap-3 items-end">
            <SettingsField label="Window" value={settings.window} onChange={v => setSettings((s) => ({ ...s, window: v }))} options={['6h', '12h', '24h', '3d', '7d']} />
            <SettingsField label="Min Mentions" value={String(settings.min_mentions)} onChange={v => setSettings((s) => ({ ...s, min_mentions: Number(v) }))} options={['1', '2', '3', '5', '10', '20']} />
            <SettingsField label="Min Users" value={String(settings.min_users)} onChange={v => setSettings((s) => ({ ...s, min_users: Number(v) }))} options={['1', '2', '3', '5', '10']} />
            <SettingsField label="Limit" value={String(settings.limit)} onChange={v => setSettings((s) => ({ ...s, limit: Number(v) }))} options={['10', '25', '50', '100', '200']} />
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* ── Left: Sources ──────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
              <Search size={14} className="text-blue-400" />
              Search Queries ({enabledSources.length})
            </h2>
            <div className="flex gap-2 mb-3">
              <input
                ref={inputRef}
                type="text"
                value={newQuery}
                onChange={e => setNewQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddSource()}
                placeholder="@handle, keyword, or 0x address"
                className="flex-1 bg-[#1a1a24] border border-[#1e1e2e] rounded-lg px-3 py-1.5 text-xs text-[#e4e4e7] placeholder-[#52525b] focus:outline-none focus:border-blue-500/50"
              />
              <button onClick={handleAddSource} disabled={adding || !newQuery.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-40 transition-all">
                <Plus size={12} /> Add
              </button>
            </div>
            {srcLoading ? (
              <div className="flex items-center gap-2 text-sm text-[#71717a]">
                <RefreshCw size={14} className="animate-spin" /> Loading\u2026
              </div>
            ) : enabledSources.length === 0 ? (
              <p className="text-sm text-[#71717a]">
                No queries configured. Click "Run Discovery" to auto-seed defaults.
              </p>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {enabledSources.map(src => (
                  <div key={src.id} className="flex items-center justify-between gap-3 p-2.5 rounded-lg border bg-[#1a1a24] border-[#1e1e2e] hover:border-[#2e2e3e] transition-all">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded border ${SOURCE_TYPE_COLORS[src.source_type] || 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20'}`}>
                            {SOURCE_TYPE_LABELS[src.source_type] || src.source_type}
                        </span>
                        <span className="text-sm font-medium text-[#e4e4e7] truncate">{truncate(src.name, 28)}</span>
                      </div>
                      <div className="text-xs text-[#71717a] mt-1 font-mono">{truncate(src.query, 40)}</div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 text-xs text-[#71717a]">
                      {src.last_collected_at ? (
                        <span>{new Date(src.last_collected_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      ) : <AlertCircle size={12} className="text-yellow-500" />}
                      <button onClick={() => handleToggle(src.source_id)} className="p-0.5 rounded hover:bg-[#2e2e3e]">
                        <Power size={12} className={src.enabled ? 'text-green-500' : 'text-[#52525b]'} />
                      </button>
                      <button onClick={() => handleRemove(src.source_id)} className="p-0.5 rounded hover:bg-red-500/10">
                        <X size={12} className="text-[#52525b] hover:text-red-400" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {disabledSources.length > 0 && (
            <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
              <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#71717a]">
                <Power size={14} /> Inactive ({disabledSources.length})
              </h2>
              <div className="space-y-1.5 max-h-40 overflow-y-auto">
                {disabledSources.map(src => (
                  <div key={src.id} className="flex items-center justify-between gap-2 text-xs text-[#71717a] py-1">
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-zinc-600" />
                      <span className="font-mono">{truncate(src.query, 30)}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <button onClick={() => handleToggle(src.source_id)} className="p-0.5 rounded hover:bg-[#2e2e3e]">
                        <Power size={12} className="text-[#52525b] hover:text-green-400" />
                      </button>
                      <button onClick={() => handleRemove(src.source_id)} className="p-0.5 rounded hover:bg-red-500/10">
                        <X size={12} className="text-[#52525b] hover:text-red-400" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Right: Discovered Tokens ────────────────────────── */}
        <div className="lg:col-span-3">
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
              <TrendingUp size={14} className="text-blue-400" />
              Top Discovered Tokens ({settings.window})
              <span className="text-xs text-[#71717a] ml-auto">{discovery?.total_tokens ?? 0} tokens</span>
            </h2>

            {discLoading ? (
              <div className="flex items-center gap-2 text-sm text-[#71717a] py-8 justify-center">
                <RefreshCw size={14} className="animate-spin" /> Loading\u2026
              </div>
            ) : !discovery?.tokens?.length ? (
              <div className="flex flex-col items-center justify-center py-12 text-[#71717a]">
                <Layers size={32} className="mb-3 opacity-50" />
                <p className="text-sm">No tokens discovered yet</p>
                <p className="text-xs mt-1">Click "Run Discovery" and set TWITTER_USERNAME in .env</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-[#71717a] border-b border-[#1e1e2e]">
                      <th className="text-left py-2 px-2 w-8">#</th>
                      <th className="text-left py-2 px-2">Token</th>
                      <th className="text-left py-2 px-2 hidden sm:table-cell">Chain</th>
                      <th className="text-right py-2 px-2">Mentions</th>
                      <th className="text-right py-2 px-2 hidden md:table-cell">Users</th>
                      <th className="text-right py-2 px-2 hidden lg:table-cell">Engagement</th>
                      <th className="text-right py-2 px-2">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {discovery.tokens.map((token, i) => (
                      <React.Fragment key={token.token_address}>
                        <tr className="border-b border-[#1a1a24] hover:bg-[#1a1a24] transition-colors cursor-pointer"
                          onClick={() => setExpandedToken(expandedToken === i ? null : i)}>
                          <td className="py-2.5 px-2 text-[#71717a] text-xs font-mono">{token.rank}</td>
                          <td className="py-2.5 px-2">
                            <div className="flex items-center gap-2">
                              <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${CHAIN_COLORS[token.chain] || 'bg-zinc-500/15 text-zinc-400'}`}>
                                {token.chain}
                              </span>
                              <span className="font-medium text-[#e4e4e7]">${token.name || token.symbol}</span>
                            </div>
                            <div className="text-[10px] text-[#52525b] font-mono mt-0.5">{token.token_address}</div>
                          </td>
                          <td className="py-2.5 px-2 hidden sm:table-cell capitalize text-[#a1a1aa] text-xs">{token.chain}</td>
                          <td className="py-2.5 px-2 text-right">
                            <span className="font-mono text-[#e4e4e7] font-medium">{token.mention_count}</span>
                          </td>
                          <td className="py-2.5 px-2 text-right hidden md:table-cell">
                            <span className="font-mono text-[#71717a]">{token.unique_user_count}</span>
                          </td>
                          <td className="py-2.5 px-2 text-right hidden lg:table-cell">
                            <span className="font-mono text-[#71717a]">{token.total_engagement}</span>
                          </td>
                          <td className="py-2.5 px-2 text-right">
                            <span className="font-mono text-[#e4e4e7] font-medium">{token.total_score}</span>
                          </td>
                        </tr>
                        {expandedToken === i && (
                          <tr key={`${token.token_address}-exp`}>
                            <td colSpan={7} className="bg-[#0e0e14] px-4 py-3 border-b border-[#1e1e2e]">
                              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                                <div>
                                  <span className="text-[#52525b]">Address</span>
                                  <div className="font-mono text-[#a1a1aa] mt-0.5 break-all">{token.token_address}</div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Methods</span>
                                  <div className="flex flex-wrap gap-1 mt-0.5">
                                    {token.discovery_methods.map(m => (
                                      <span key={m} className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 text-[10px]">{m}</span>
                                    ))}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Sources</span>
                                  <div className="flex flex-wrap gap-1 mt-0.5">
                                    {token.source_names.slice(0, 3).map(s => (
                                      <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-[#1e1e2e] text-[#a1a1aa]">{s}</span>
                                    ))}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">KPIs</span>
                                  <div className="text-[#a1a1aa] mt-0.5 font-mono text-[11px]">
                                    {token.mention_count} mentions · {token.unique_user_count} users<br />
                                    {token.total_engagement} engagement · {token.authority_mentions} authority
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Last Seen</span>
                                  <div className="text-[#a1a1aa] mt-0.5">
                                    {new Date(token.last_seen_in_window).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Score</span>
                                  <div className="text-[#a1a1aa] mt-0.5 font-mono">{token.total_score}</div>
                                </div>
                                {token.dex_url && (
                                  <div className="col-span-2">
                                    <span className="text-[#52525b]">DEX Link</span>
                                    <a href={token.dex_url} target="_blank" rel="noopener noreferrer"
                                      className="flex items-center gap-1 text-blue-400 hover:text-blue-300 mt-0.5 truncate"
                                      onClick={e => e.stopPropagation()}>
                                      <ExternalLink size={10} /> {truncate(token.dex_url, 50)}
                                    </a>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Helper Components ──────────────────────────────────────────────────

function StatCard({ icon: Icon, label, value, color, bg, loading, sub }: {
  icon: React.FC<{ size?: number; className?: string }>;
  label: string; value: React.ReactNode; color: string; bg: string;
  loading?: boolean; sub?: string;
}) {
  return (
    <div className={`${bg} border border-[#1e1e2e] rounded-xl p-4`}>
      <div className="flex items-center gap-2 text-xs text-[#a1a1aa] mb-1">
        <Icon size={12} className={color} />
        {label}
      </div>
      <div className={`text-xl font-bold ${color}`}>
        {loading ? <RefreshCw size={16} className="animate-spin opacity-60" /> : value ?? 0}
      </div>
      {sub && <div className="text-[10px] text-[#52525b] mt-0.5">{sub}</div>}
    </div>
  );
}

function SettingsField({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: string[];
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] text-[#52525b] uppercase tracking-wider">{label}</span>
      <div className="flex gap-1">
        {options.map(o => (
          <button key={o} onClick={() => onChange(o)}
            className={`px-2 py-1 rounded text-xs font-mono transition-all ${
              value === o ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'bg-[#1a1a24] text-[#71717a] border border-[#1e1e2e] hover:border-[#2e2e3e]'
            }`}>
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}
