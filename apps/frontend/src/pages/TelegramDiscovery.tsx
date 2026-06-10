import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Hash, Radio, Search, RefreshCw, ExternalLink, TrendingUp, Layers, AlertCircle, Settings, Play, Plus, X, Power } from 'lucide-react';
import { useTelegramDiscovery, useTelegramSources, useTelegramStats } from '../hooks/useApi';
import { telegramApi } from '../api/client';
import GroupMentionsPanel from '../components/GroupMentionsPanel';

const SOURCE_TYPE_LABELS: Record<string, string> = {
  alpha_group: 'Alpha',
  trend_group: 'Trends',
  meme_group: 'Memes',
  trading_group: 'Trading',
  chain_group: 'Chain',
};

const SOURCE_TYPE_COLORS: Record<string, string> = {
  alpha_group: 'bg-green-500/10 text-green-400 border-green-500/20',
  trend_group: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  meme_group: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  trading_group: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  chain_group: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
};

const CHAIN_COLORS: Record<string, string> = {
  ethereum: 'bg-blue-500/15 text-blue-400',
  solana: 'bg-gradient-to-r from-purple-500/15 to-cyan-500/15 text-purple-400',
  bsc: 'bg-yellow-500/15 text-yellow-400',
  base: 'bg-blue-600/15 text-blue-300',
};

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function loadSettings(): Partial<{ window: string; limit: number; min_mentions: number; min_groups: number; min_unique_users: number }> {
  try {
    const raw = localStorage.getItem('telegram_discovery_settings');
    if (raw) return JSON.parse(raw);
  } catch {}
  return {};
}

function saveSettings(s: Record<string, unknown>) {
  localStorage.setItem('telegram_discovery_settings', JSON.stringify(s));
}

export default function TelegramDiscovery() {
  const [settings, setSettings] = useState<{ window: string; limit: number; min_mentions: number; min_groups: number; min_unique_users: number }>(() => ({
    window: '24h',
    limit: 50,
    min_mentions: 1,
    min_groups: 1,
    min_unique_users: 1,
    ...loadSettings(),
  }));
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  const { data: discovery, isLoading: discLoading, refetch: refetchDiscovery } = useTelegramDiscovery({
    window: settings.window,
    limit: settings.limit,
    min_mentions: settings.min_mentions,
    min_groups: settings.min_groups,
    min_unique_users: settings.min_unique_users,
  });
  const { data: sources, isLoading: srcLoading, refetch: refetchSources } = useTelegramSources();
  const { data: stats, refetch: refetchStats } = useTelegramStats();
  const [expandedToken, setExpandedToken] = useState<number | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [newGroup, setNewGroup] = useState('');
  const [adding, setAdding] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleAddGroup = async () => {
    const ident = newGroup.trim();
    if (!ident || adding) return;
    setAdding(true);
    try {
      await telegramApi.addSource(ident);
      setNewGroup('');
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to add source', e);
    }
    setAdding(false);
  };

  const handleRemove = async (sourceId: string) => {
    try {
      await telegramApi.removeSource(sourceId);
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to remove source', e);
    }
  };

  const handleToggle = async (sourceId: string) => {
    try {
      await telegramApi.toggleSource(sourceId);
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to toggle source', e);
    }
  };

  const [resetting, setResetting] = useState(false);
  const handleReset = async () => {
    if (collecting || resetting) return;
    setResetting(true);
    try {
      await telegramApi.reset();
    } catch (e) {
      console.error('Reset failed', e);
    } finally {
      setResetting(false);
      refetchDiscovery();
      refetchSources();
      refetchStats();
    }
  };

  const [progress, setProgress] = useState<{
    step?: string; status?: string; group?: string; total_messages: number;
    total_tokens: number; total_mentions?: number;
    sources_done: number; sources_total: number;
    enriched?: number; failed?: number;
    ai_kept?: number; ai_discarded?: number; ai_pending?: number;
    progress_pct?: number;
  } | null>(null);
  const [collectError, setCollectError] = useState<string | null>(null);

  const handleCollect = async () => {
    setCollecting(true);
    setCollectError(null);
    setProgress({
      step: 'reset', status: 'Starting...', total_messages: 0, total_tokens: 0,
      sources_done: 0, sources_total: sources?.filter(s => s.enabled).length || 60,
    });

    try {
      const res = await fetch(`/api/v1/telegram/collect?window=${settings.window}`, { method: 'POST' });
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events from buffer
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
            // Empty line = end of event
            try {
              const data = JSON.parse(currentData);
              if (currentEvent === 'progress' || currentEvent === 'done') {
                setProgress(data);
                // Refetch when enrichment/dedup/ai steps complete to show updated data
                if (data.refetch) {
                  refetchDiscovery();
                  refetchStats();
                }
              }
              if (currentEvent === 'done') {
                setCollecting(false);
                refetchDiscovery();
                refetchSources();
                refetchStats();
                return;
              }
              if (currentEvent === 'error') {
                setProgress({ ...data, status: 'error', group: data.message || '' });
                setCollecting(false);
                setCollectError(data.message || 'Collection failed');
                refetchDiscovery();
                refetchSources();
                refetchStats();
                return;
              }
            } catch {}
            currentEvent = '';
            currentData = '';
          } else if (line.startsWith(':')) {
            // heartbeat comment, ignore
          } else {
            // continuation line or partial - save back to buffer
            buffer += line + '\n';
          }
        }
      }
      // Stream ended without "done" event
      setCollecting(false);
      refetchDiscovery();
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('SSE stream failed', e);
      setCollecting(false);
      setCollectError(String(e));
      setProgress(prev => prev ? { ...prev, status: 'error', group: String(e) } : null);
    }
  };

  const enabledSources = sources?.filter(s => s.enabled) ?? [];
  const activeGroup = progress?.group || '';
  const disabledSources = sources?.filter(s => !s.enabled) ?? [];
  const lastDiscoveryTime = enabledSources
    .map(s => s.last_collected_at)
    .filter(Boolean)
    .sort()
    .reverse()[0] || null;
  const lastDiscoveryLabel = lastDiscoveryTime
    ? new Date(lastDiscoveryTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className="px-2 py-3">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-bold text-[#e4e4e7] flex items-center gap-2">
            <Radio size={24} className="text-indigo-400" />
            Telegram Discovery
          </h1>
          <p className="text-sm mt-1 text-[#71717a]">
            {stats?.enabled_sources ?? 0} groups · {stats?.candidate_tokens ?? 0} tokens · {stats?.total_mentions ?? 0} mentions
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            disabled={collecting || resetting}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              resetting
                ? 'bg-red-500/20 text-red-300 cursor-wait'
                : 'bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 active:scale-95'
            }`}
          >
            {resetting ? (
              <><RefreshCw size={14} className="animate-spin" /> Resetting…</>
            ) : (
              <><X size={14} /> Reset All</>
            )}
          </button>
          <button
            onClick={handleCollect}
            disabled={collecting || resetting}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              collecting
                ? 'bg-indigo-500/20 text-indigo-300 cursor-wait'
                : 'bg-indigo-500 text-white hover:bg-indigo-600 active:scale-95'
            }`}
          >
            {collecting ? (
              <><RefreshCw size={14} className="animate-spin" /> Collecting…</>
            ) : (
              <><Play size={14} /> Run Discovery</>
            )}
          </button>
        </div>
      </div>

      {/* ── Stats Row ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <StatCard
          icon={Radio} label="Groups" value={enabledSources.length}
          color="text-indigo-400" bg="bg-indigo-500/10" loading={collecting}
          sub={collecting && progress?.sources_total ? `${progress.sources_done}/${progress.sources_total}` : (lastDiscoveryLabel ? `Last: ${lastDiscoveryLabel}` : undefined)}
        />
        <StatCard
          icon={Search} label="Tokens" value={collecting && progress ? progress.total_tokens : (stats?.candidate_tokens ?? 0)}
          color="text-green-400" bg="bg-green-500/10" loading={collecting || discLoading}
          sub={collecting && progress?.enriched != null ? `✓${progress.enriched} enriched` : undefined}
        />
        <StatCard
          icon={MessageSquare} label="Mentions" value={collecting && progress && progress.total_mentions != null ? progress.total_mentions : (stats?.total_mentions ?? 0)}
          color="text-yellow-400" bg="bg-yellow-500/10" loading={collecting || discLoading}
        />
        <StatCard
          icon={Hash} label="Messages" value={collecting && progress ? progress.total_messages : (stats?.messages_stored ?? 0)}
          color="text-cyan-400" bg="bg-cyan-500/10" loading={collecting || discLoading}
          sub={collecting && progress?.ai_kept != null ? `AI: ${progress.ai_kept}✓ ${progress.ai_discarded}✗` : undefined}
        />
      </div>

      {/* ── Progress Bar ──────────────────────────────────────────── */}
      {collecting && progress && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-[#a1a1aa]">
              {progress.step === 'reset' ? 'Clearing previous data…' :
               progress.step === 'collect' ? `Scanning groups (${progress.sources_done}/${progress.sources_total})` :
               progress.step === 'extract' ? `Extracting tokens — ${progress.status || ''}` :
               progress.step === 'enrich' ? `Enriching tokens — ${progress.status || ''}` :
               progress.step === 'dedup' ? 'Removing duplicates…' :
               progress.step === 'ai' ? `AI Evaluation — ${progress.status || ''}` :
               progress.step === 'done' ? 'Complete!' :
               progress.status || 'Working…'}
            </span>
            {(progress.progress_pct != null || progress.sources_total > 0) && (
              <span className="text-xs text-indigo-400 font-mono">
                {progress.progress_pct != null ? `${progress.progress_pct}%` :
                  `${Math.round((progress.sources_done / progress.sources_total) * 100)}%`}
              </span>
            )}
          </div>
          <div className="w-full bg-[#1a1a24] rounded-full h-2 border border-[#1e1e2e]">
            <div
              className={`h-full rounded-full transition-all duration-500 ease-out ${
                progress.step === 'enrich' ? 'bg-emerald-500' :
                progress.step === 'ai' ? 'bg-purple-500' :
                progress.step === 'dedup' ? 'bg-amber-500' :
                'bg-indigo-500'
              }`}
              style={{ width: `${progress.progress_pct != null ? progress.progress_pct :
                progress.sources_total > 0 ? (progress.sources_done / progress.sources_total) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      {/* ── Error Banner ─────────────────────────────────────────── */}
      {collectError && (
        <div className="mb-4 p-4 rounded-lg bg-red-500/10 border border-red-500/20 flex items-start gap-3">
          <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-red-400 font-medium">Collection Error</p>
            <p className="text-xs text-red-300/70 mt-0.5 break-all">{collectError}</p>
          </div>
          <button
            onClick={() => setCollectError(null)}
            className="p-0.5 rounded hover:bg-red-500/10 transition-colors shrink-0"
          >
            <X size={14} className="text-red-400" />
          </button>
        </div>
      )}

      {/* ── Settings Bar ──────────────────────────────────────────── */}
      <div className="mb-4">
        <button
          onClick={() => setShowSettings(!showSettings)}
          className="flex items-center gap-1.5 text-xs text-[#71717a] hover:text-[#a1a1aa] transition-colors"
        >
          <Settings size={12} />
          {showSettings ? 'Hide' : 'Filters'}: window={settings.window} · mentions≥{settings.min_mentions} · groups≥{settings.min_groups} · users≥{settings.min_unique_users} · limit={settings.limit}
        </button>
        {showSettings && (
          <div className="mt-2 p-3 rounded-lg bg-[#13131a] border border-[#1e1e2e] flex flex-wrap gap-3 items-end">
            <SettingsField label="Window" value={settings.window} onChange={v => setSettings((s: typeof settings) => ({ ...s, window: v }))} options={['15m', '30m', '60m', '6h', '24h']} />
            <SettingsField label="Min Mentions" value={String(settings.min_mentions)} onChange={v => setSettings((s: typeof settings) => ({ ...s, min_mentions: Number(v) }))} options={['1', '2', '3', '5', '10', '20']} />
            <SettingsField label="Min Groups" value={String(settings.min_groups)} onChange={v => setSettings((s: typeof settings) => ({ ...s, min_groups: Number(v) }))} options={['1', '2', '3', '5', '10']} />
            <SettingsField label="Min Users" value={String(settings.min_unique_users)} onChange={v => setSettings((s: typeof settings) => ({ ...s, min_unique_users: Number(v) }))} options={['1', '2', '3', '5', '10']} />
            <SettingsField label="Limit" value={String(settings.limit)} onChange={v => setSettings((s: typeof settings) => ({ ...s, limit: Number(v) }))} options={['10', '25', '50', '100', '200']} />
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* ── Left: Sources ──────────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-6">
          {/* Enabled Groups */}
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
              <Radio size={14} className="text-green-400" />
              Enabled Groups ({enabledSources.length})
            </h2>
            {/* Add Group Input */}
            <div className="flex gap-2 mb-3">
              <input
                ref={inputRef}
                type="text"
                value={newGroup}
                onChange={e => setNewGroup(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddGroup()}
                placeholder="@groupname or chat ID"
                className="flex-1 bg-[#1a1a24] border border-[#1e1e2e] rounded-lg px-3 py-1.5 text-xs text-[#e4e4e7] placeholder-[#52525b] focus:outline-none focus:border-indigo-500/50"
              />
              <button
                onClick={handleAddGroup}
                disabled={adding || !newGroup.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-500 text-white hover:bg-indigo-600 disabled:opacity-40 transition-all"
              >
                <Plus size={12} /> Add
              </button>
            </div>
            {srcLoading ? (
              <div className="flex items-center gap-2 text-sm text-[#71717a]">
                <RefreshCw size={14} className="animate-spin" /> Loading…
              </div>
            ) : enabledSources.length === 0 ? (
              <p className="text-sm text-[#71717a]">
                No groups enabled. Set <code className="text-xs bg-[#1e1e2e] px-1.5 py-0.5 rounded">TELEGRAM_GROUPS=@group1,@group2</code> in .env
              </p>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {enabledSources.map(src => {
                  const isActive = collecting && (activeGroup === src.name || activeGroup === src.telegram_identifier);
                  return (
                  <div
                    key={src.id}
                    className={`flex items-center justify-between gap-3 p-2.5 rounded-lg border transition-all ${
                      isActive
                        ? 'bg-indigo-500/10 border-indigo-500/40 shadow-[0_0_8px_rgba(99,102,241,0.15)]'
                        : 'bg-[#1a1a24] border-[#1e1e2e] hover:border-[#2e2e3e]'
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded border ${SOURCE_TYPE_COLORS[src.source_type] || 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20'}`}>
                          {SOURCE_TYPE_LABELS[src.source_type] || src.source_type}
                        </span>
                        <span className="text-sm font-medium text-[#e4e4e7] truncate">{truncate(src.name, 28)}</span>
                      </div>
                      <div className="text-xs text-[#71717a] mt-1 font-mono">{src.telegram_identifier}</div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 text-xs text-[#71717a]">
                      {src.last_collected_at ? (
                        <span title={src.last_collected_at}>
                          {new Date(src.last_collected_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      ) : (
                        <span title="Not yet collected"><AlertCircle size={12} className="text-yellow-500" /></span>
                      )}
                      <button
                        onClick={() => handleToggle(src.source_id)}
                        className="p-0.5 rounded hover:bg-[#2e2e3e] transition-colors"
                        title="Toggle enabled"
                      >
                        <Power size={12} className={src.enabled ? 'text-green-500' : 'text-[#52525b]'} />
                      </button>
                      <button
                        onClick={() => handleRemove(src.source_id)}
                        className="p-0.5 rounded hover:bg-red-500/10 transition-colors"
                        title="Remove group"
                      >
                        <X size={12} className="text-[#52525b] hover:text-red-400" />
                      </button>
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Disabled Groups */}
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
                      <span className="font-mono">{src.telegram_identifier || src.source_id}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleToggle(src.source_id)}
                        className="p-0.5 rounded hover:bg-[#2e2e3e] transition-colors"
                        title="Re-enable"
                      >
                        <Power size={12} className="text-[#52525b] hover:text-green-400" />
                      </button>
                      <button
                        onClick={() => handleRemove(src.source_id)}
                        className="p-0.5 rounded hover:bg-red-500/10 transition-colors"
                        title="Remove"
                      >
                        <X size={12} className="text-[#52525b] hover:text-red-400" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Right: Discovered Tokens ────────────────────────────── */}
        <div className="lg:col-span-3">
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
              <TrendingUp size={14} className="text-green-400" />
              Top Discovered Tokens ({settings.window})
              <span className="text-xs text-[#71717a] ml-auto">
                {discovery?.total_tokens ?? 0} tokens
              </span>
            </h2>

            {discLoading ? (
              <div className="flex items-center gap-2 text-sm text-[#71717a] py-8 justify-center">
                <RefreshCw size={14} className="animate-spin" /> Loading…
              </div>
            ) : !discovery?.tokens?.length ? (
              <div className="flex flex-col items-center justify-center py-12 text-[#71717a]">
                <Layers size={32} className="mb-3 opacity-50" />
                <p className="text-sm">No tokens discovered yet</p>
                <p className="text-xs mt-1">Run <code className="text-xs bg-[#1e1e2e] px-1.5 py-0.5 rounded">python -m app.telegram_discovery.collect</code></p>
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
                      <th className="text-right py-2 px-2 hidden md:table-cell">Groups</th>
                      <th className="text-left py-2 px-2 hidden lg:table-cell">Sources</th>
                    </tr>
                  </thead>
                  <tbody>
                    {discovery.tokens.map((token, i) => (
                      <React.Fragment key={token.token_address}>
                        <tr
                          key={token.token_address}
                          className="border-b border-[#1a1a24] hover:bg-[#1a1a24] transition-colors cursor-pointer"
                          onClick={() => setExpandedToken(expandedToken === i ? null : i)}
                        >
                          <td className="py-2.5 px-2 text-[#71717a] text-xs font-mono">{token.rank}</td>
                          <td className="py-2.5 px-2">
                            <div className="flex items-center gap-2">
                              <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${CHAIN_COLORS[token.chain] || 'bg-zinc-500/15 text-zinc-400'}`}>
                                {token.chain}
                              </span>
                              <span className="font-medium text-[#e4e4e7]">{token.name || token.symbol}</span>
                              <span className="text-xs text-[#71717a] hidden sm:inline">${token.symbol}</span>
                            </div>
                            <div className="text-[10px] text-[#52525b] font-mono mt-0.5">
                              {token.token_address}
                            </div>
                          </td>
                          <td className="py-2.5 px-2 hidden sm:table-cell capitalize text-[#a1a1aa] text-xs">{token.chain}</td>
                          <td className="py-2.5 px-2 text-right">
                            <span className="font-mono text-[#e4e4e7] font-medium">{token.mention_count}</span>
                            {(token.total_reactions > 0 || token.total_views > 0) && (
                              <div className="flex items-center justify-end gap-1.5 mt-0.5">
                                {token.total_reactions > 0 && (
                                  <span className="text-[10px] text-emerald-400" title="Reactions">👍{token.total_reactions}</span>
                                )}
                                {token.total_views > 0 && (
                                  <span className="text-[10px] text-blue-400" title="Replies">💬{token.total_views}</span>
                                )}
                              </div>
                            )}
                          </td>
                          <td className="py-2.5 px-2 text-right hidden md:table-cell">
                            <span className="font-mono text-[#71717a]">{token.unique_user_count}</span>
                          </td>
                          <td className="py-2.5 px-2 text-right hidden md:table-cell">
                            <span className={`font-mono font-medium ${
                              token.group_count >= 5 ? 'text-green-400' :
                              token.group_count >= 3 ? 'text-emerald-400' :
                              token.group_count >= 2 ? 'text-amber-400' :
                              'text-[#71717a]'
                            }`}>{token.group_count}</span>
                          </td>
                          <td className="py-2.5 px-2 hidden lg:table-cell">
                            <div className="flex flex-wrap gap-1">
                              {token.source_names.slice(0, 2).map(s => (
                                <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-[#1e1e2e] text-[#a1a1aa] truncate max-w-[100px]">
                                  {s.replace('@', '')}
                                </span>
                              ))}
                              {token.source_names.length > 2 && (
                                <span className="text-[10px] text-[#52525b]">+{token.source_names.length - 2}</span>
                              )}
                            </div>
                          </td>
                        </tr>
                        {/* Expanded row */}
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
                                      <span key={m} className="px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 text-[10px]">{m}</span>
                                    ))}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">First Seen</span>
                                  <div className="text-[#a1a1aa] mt-0.5">
                                    {new Date(token.first_seen_in_window).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Last Seen</span>
                                  <div className="text-[#a1a1aa] mt-0.5">
                                    {new Date(token.last_seen_in_window).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Reactions</span>
                                  <div className="text-[#10b981] mt-0.5 font-mono">{token.total_reactions ?? 0}</div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Replies</span>
                                  <div className="text-[#60a5fa] mt-0.5 font-mono">{token.total_views ?? 0}</div>
                                </div>
                                {token.ai_decision && (
                                  <div className="col-span-2 sm:col-span-4">
                                    <span className="text-[#52525b]">AI Decision</span>
                                    <div className="flex items-center gap-1.5 mt-0.5">
                                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                        token.ai_decision === 'keep' ? 'bg-green-500/10 text-green-400' :
                                        token.ai_decision === 'discard' ? 'bg-red-500/10 text-red-400' :
                                        'bg-yellow-500/10 text-yellow-400'
                                      }`}>
                                        {token.ai_decision.toUpperCase()}
                                      </span>
                                      {token.ai_confidence != null && (
                                        <span className="text-[10px] text-[#52525b]">
                                          {Math.round(token.ai_confidence * 100)}% confidence
                                        </span>
                                      )}
                                    </div>
                                    {token.ai_reasoning && (
                                      <div className="mt-1.5 p-2 rounded bg-[#13131a] border border-[#1e1e2e]">
                                        <p className="text-xs text-[#a1a1aa] leading-relaxed">{token.ai_reasoning}</p>
                                      </div>
                                    )}
                                    {token.ai_red_flags?.length > 0 && (
                                      <div className="flex flex-wrap gap-1 mt-1.5">
                                        {token.ai_red_flags.map((flag: string) => (
                                          <span key={flag} className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 text-[10px]">
                                            🚩 {flag}
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                    {token.ai_positive_signals?.length > 0 && (
                                      <div className="flex flex-wrap gap-1 mt-1">
                                        {token.ai_positive_signals.map((sig: string) => (
                                          <span key={sig} className="px-1.5 py-0.5 rounded bg-green-500/10 text-green-400 text-[10px]">
                                            ✅ {sig}
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}
                                {token.dex_url && (
                                  <div className="col-span-2">
                                    <span className="text-[#52525b]">DEX Link</span>
                                    <a
                                      href={token.dex_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="flex items-center gap-1 text-indigo-400 hover:text-indigo-300 mt-0.5 truncate"
                                      onClick={e => e.stopPropagation()}
                                    >
                                      <ExternalLink size={10} /> {truncate(token.dex_url, 50)}
                                    </a>
                                  </div>
                                )}
                              </div>
                              {/* ── Group Mentions Breakdown ───────────────── */}
                              {token.source_mentions && Object.keys(token.source_mentions).length > 0 && (
                                <div className="mt-3 pt-3 border-t border-[#1e1e2e]">
                                  <GroupMentionsPanel
                                    sourceMentions={token.source_mentions}
                                    totalMentions={token.mention_count}
                                  />
                                </div>
                              )}
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

function StatCard({ icon: Icon, label, value, color, bg, loading, sub }: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: number;
  color: string;
  bg: string;
  loading?: boolean;
  sub?: string;
}) {
  return (
    <div className={`${bg} border border-[#1e1e2e] rounded-xl p-4 transition-all ${loading ? 'border-indigo-500/30 shadow-[0_0_12px_rgba(99,102,241,0.1)]' : ''}`}>
      <div className="flex items-center gap-2 mb-1">
        <Icon size={14} className={loading ? 'text-indigo-400 animate-pulse' : color} />
        <span className="text-xs text-[#71717a]">{label}</span>
      </div>
      <div className={`text-2xl font-bold ${loading ? 'text-indigo-400' : color}`}>
        {loading && sub === undefined ? (
          <span className="inline-flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
            <span className="text-sm">...</span>
          </span>
        ) : (
          value
        )}
      </div>
      {sub && <div className="text-xs text-[#71717a] mt-0.5">{sub}</div>}
    </div>
  );
}

function SettingsField({ label, value, onChange, options }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] text-[#52525b] uppercase tracking-wider">{label}</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="bg-[#1a1a24] border border-[#1e1e2e] rounded-md px-2 py-1 text-xs text-[#e4e4e7] focus:outline-none focus:border-indigo-500/50"
      >
        {options.map(o => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}
