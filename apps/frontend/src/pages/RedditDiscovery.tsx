import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Hash, MessageCircle, Search, RefreshCw, ExternalLink, TrendingUp, Layers, AlertCircle, Settings, Play, Plus, X, Power, ThumbsUp } from 'lucide-react';
import { useRedditDiscovery, useRedditSources, useRedditStats } from '../hooks/useApi';
import { redditApi } from '../api/client';

const SOURCE_TYPE_LABELS: Record<string, string> = {
  general_crypto: 'General',
  meme_coins: 'Memes',
  trading: 'Trading',
  defi: 'DeFi',
  chain_specific: 'Chain',
};

const SOURCE_TYPE_COLORS: Record<string, string> = {
  general_crypto: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  meme_coins: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  trading: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  defi: 'bg-green-500/10 text-green-400 border-green-500/20',
  chain_specific: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
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

function loadSettings(): Partial<{ window: string; limit: number; min_mentions: number; min_users: number }> {
  try {
    const raw = localStorage.getItem('reddit_discovery_settings');
    if (raw) return JSON.parse(raw);
  } catch {}
  return {};
}

function saveSettings(s: Record<string, unknown>) {
  localStorage.setItem('reddit_discovery_settings', JSON.stringify(s));
}

export default function RedditDiscovery() {
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

  const { data: discovery, isLoading: discLoading, refetch: refetchDiscovery } = useRedditDiscovery({
    window: settings.window,
    limit: settings.limit,
    min_mentions: settings.min_mentions,
    min_users: settings.min_users,
  });
  const { data: sources, isLoading: srcLoading, refetch: refetchSources } = useRedditSources();
  const { data: stats, refetch: refetchStats } = useRedditStats();
  const [expandedToken, setExpandedToken] = useState<number | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [newSubreddit, setNewSubreddit] = useState('');
  const [adding, setAdding] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleAddSubreddit = async () => {
    const name = newSubreddit.trim();
    if (!name || adding) return;
    setAdding(true);
    try {
      await redditApi.addSource(name);
      setNewSubreddit('');
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to add source', e);
    }
    setAdding(false);
  };

  const handleRemove = async (sourceId: string) => {
    try {
      await redditApi.removeSource(sourceId);
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to remove source', e);
    }
  };

  const handleToggle = async (sourceId: string) => {
    try {
      await redditApi.toggleSource(sourceId);
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('Failed to toggle source', e);
    }
  };

  const [progress, setProgress] = useState<{
    status: string; subreddit: string; total_posts: number;
    total_tokens: number; total_mentions?: number;
    sources_done: number; sources_total: number;
  } | null>(null);

  const handleCollect = async () => {
    setCollecting(true);
    setProgress({
      status: 'starting', subreddit: '', total_posts: 0, total_tokens: 0,
      sources_done: 0, sources_total: sources?.filter(s => s.enabled).length || 6,
    });

    try {
      const res = await fetch(`/api/v1/reddit/collect?window=${settings.window}`, { method: 'POST' });
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');

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
              const data = JSON.parse(currentData);
              if (currentEvent === 'progress' || currentEvent === 'done') {
                setProgress(data);
              }
              if (currentEvent === 'done') {
                setCollecting(false);
                refetchDiscovery();
                refetchSources();
                refetchStats();
                return;
              }
              if (currentEvent === 'error') {
                setProgress({ ...data, status: 'error', subreddit: data.message || '' });
                setCollecting(false);
                refetchDiscovery();
                refetchSources();
                refetchStats();
                return;
              }
            } catch {}
            currentEvent = '';
            currentData = '';
          } else if (line.startsWith(':')) {
            // heartbeat comment
          } else {
            buffer += line + '\n';
          }
        }
      }
      setCollecting(false);
      refetchDiscovery();
      refetchSources();
      refetchStats();
    } catch (e) {
      console.error('SSE stream failed', e);
      setCollecting(false);
      setProgress(prev => prev ? { ...prev, status: 'error', subreddit: String(e) } : null);
    }
  };

  const enabledSources = sources?.filter(s => s.enabled) ?? [];
  const activeSubreddit = progress?.subreddit || '';
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
    <div className="max-w-7xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[#e4e4e7] flex items-center gap-2">
            <MessageCircle size={24} className="text-orange-400" />
            Reddit Discovery
          </h1>
          <p className="text-sm mt-1 text-[#71717a]">
            {stats?.enabled_sources ?? 0} subreddits · {stats?.candidate_tokens ?? 0} tokens · {stats?.total_mentions ?? 0} mentions · {stats?.total_upvotes ?? 0} upvotes
          </p>
        </div>
        <button
          onClick={handleCollect}
          disabled={collecting}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            collecting
              ? 'bg-orange-500/20 text-orange-300 cursor-wait'
              : 'bg-orange-500 text-white hover:bg-orange-600 active:scale-95'
          }`}
        >
          {collecting ? (
            <><RefreshCw size={14} className="animate-spin" /> Collecting…</>
          ) : (
            <><Play size={14} /> Run Discovery</>
          )}
        </button>
      </div>

      {/* ── Stats Row ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3 mb-6">
        <StatCard
          icon={MessageCircle} label="Subreddits" value={enabledSources.length}
          color="text-orange-400" bg="bg-orange-500/10" loading={collecting}
          sub={collecting && progress ? `${progress.sources_done}/${progress.sources_total}` : (lastDiscoveryLabel ? `Last: ${lastDiscoveryLabel}` : undefined)}
        />
        <StatCard
          icon={Search} label="Tokens" value={collecting && progress ? progress.total_tokens : (discovery?.total_tokens ?? 0)}
          color="text-green-400" bg="bg-green-500/10" loading={collecting || discLoading}
        />
        <StatCard
          icon={Hash} label="Mentions" value={collecting && progress && progress.total_mentions != null ? progress.total_mentions : (discovery?.tokens?.reduce((s, t) => s + t.mention_count, 0) ?? 0)}
          color="text-yellow-400" bg="bg-yellow-500/10" loading={collecting || discLoading}
        />
        <StatCard
          icon={MessageSquare} label="Posts" value={collecting && progress ? progress.total_posts : (discovery?.total_posts ?? 0)}
          color="text-cyan-400" bg="bg-cyan-500/10" loading={collecting || discLoading}
        />
        <StatCard
          icon={MessageSquare} label="Comments" value={discovery?.total_comments ?? 0}
          color="text-purple-400" bg="bg-purple-500/10" loading={discLoading}
        />
        <StatCard
          icon={ThumbsUp} label="Upvotes" value={discovery?.total_upvotes ?? 0}
          color="text-pink-400" bg="bg-pink-500/10" loading={discLoading}
        />
      </div>

      {/* ── Progress Bar ──────────────────────────────────────────── */}
      {collecting && progress && progress.sources_total > 0 && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-[#a1a1aa]">
              {progress.status === 'resetting' ? 'Resetting data…' :
               progress.status === 'collecting' ? `Scanning subreddits (${progress.sources_done}/${progress.sources_total})` :
               progress.status === 'extracting' ? `Extracting tokens r/${progress.subreddit}` :
               'Collecting…'}
            </span>
            <span className="text-xs text-orange-400 font-mono">
              {Math.round((progress.sources_done / progress.sources_total) * 100)}%
            </span>
          </div>
          <div className="w-full bg-[#1a1a24] rounded-full h-2 border border-[#1e1e2e]">
            <div
              className="bg-orange-500 h-full rounded-full transition-all duration-500 ease-out"
              style={{ width: `${(progress.sources_done / progress.sources_total) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* ── Settings Bar ──────────────────────────────────────────── */}
      <div className="mb-4">
        <button
          onClick={() => setShowSettings(!showSettings)}
          className="flex items-center gap-1.5 text-xs text-[#71717a] hover:text-[#a1a1aa] transition-colors"
        >
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
        {/* ── Left: Sources ──────────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-6">
          {/* Enabled Subreddits */}
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
              <MessageCircle size={14} className="text-green-400" />
              Enabled Subreddits ({enabledSources.length})
            </h2>
            {/* Add Subreddit Input */}
            <div className="flex gap-2 mb-3">
              <input
                ref={inputRef}
                type="text"
                value={newSubreddit}
                onChange={e => setNewSubreddit(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddSubreddit()}
                placeholder="Subreddit name (e.g. CryptoCurrency)"
                className="flex-1 bg-[#1a1a24] border border-[#1e1e2e] rounded-lg px-3 py-1.5 text-xs text-[#e4e4e7] placeholder-[#52525b] focus:outline-none focus:border-orange-500/50"
              />
              <button
                onClick={handleAddSubreddit}
                disabled={adding || !newSubreddit.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-40 transition-all"
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
                No subreddits enabled. Set <code className="text-xs bg-[#1e1e2e] px-1.5 py-0.5 rounded">REDDIT_SUBREDDITS</code> in .env
              </p>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {enabledSources.map(src => {
                  const isActive = collecting && (activeSubreddit === src.subreddit_name || activeSubreddit === src.name);
                  return (
                  <div
                    key={src.id}
                    className={`flex items-center justify-between gap-3 p-2.5 rounded-lg border transition-all ${
                      isActive
                        ? 'bg-orange-500/10 border-orange-500/40 shadow-[0_0_8px_rgba(249,115,22,0.15)]'
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
                      <div className="text-xs text-[#71717a] mt-1 font-mono">r/{src.subreddit_name}</div>
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
                        title="Remove subreddit"
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

          {/* Disabled Subreddits */}
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
                      <span className="font-mono">r/{src.subreddit_name}</span>
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
                <p className="text-xs mt-1">Run <code className="text-xs bg-[#1e1e2e] px-1.5 py-0.5 rounded">python -m app.reddit_discovery.collect</code></p>
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
                      <th className="text-right py-2 px-2 hidden lg:table-cell">Posts</th>
                      <th className="text-right py-2 px-2 hidden lg:table-cell">Comments</th>
                      <th className="text-right py-2 px-2">Upvotes</th>
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
                              <span className="font-medium text-[#e4e4e7]">${token.name || token.symbol}</span>
                              {token.name && token.name !== token.symbol && (
                                <span className="text-xs text-[#71717a] hidden sm:inline">{truncate(token.name, 12)}</span>
                              )}
                            </div>
                            <div className="text-[10px] text-[#52525b] font-mono mt-0.5">
                              {token.token_address}
                            </div>
                          </td>
                          <td className="py-2.5 px-2 hidden sm:table-cell capitalize text-[#a1a1aa] text-xs">{token.chain}</td>
                          <td className="py-2.5 px-2 text-right">
                            <span className="font-mono text-[#e4e4e7] font-medium">{token.mention_count}</span>
                          </td>
                          <td className="py-2.5 px-2 text-right hidden md:table-cell">
                            <span className="font-mono text-[#71717a]">{token.unique_user_count}</span>
                          </td>
                          <td className="py-2.5 px-2 text-right hidden lg:table-cell">
                            <span className="font-mono text-[#71717a]">{token.post_count}</span>
                          </td>
                          <td className="py-2.5 px-2 text-right hidden lg:table-cell">
                            <span className="font-mono text-[#71717a]">{token.comment_count}</span>
                          </td>
                          <td className="py-2.5 px-2 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <ThumbsUp size={11} className="text-orange-400" />
                              <span className="font-mono text-[#e4e4e7] font-medium">{token.upvotes}</span>
                            </div>
                          </td>
                        </tr>
                        {/* Expanded row */}
                        {expandedToken === i && (
                          <tr key={`${token.token_address}-exp`}>
                            <td colSpan={8} className="bg-[#0e0e14] px-4 py-3 border-b border-[#1e1e2e]">
                              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                                <div>
                                  <span className="text-[#52525b]">Address</span>
                                  <div className="font-mono text-[#a1a1aa] mt-0.5 break-all">{token.token_address}</div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Methods</span>
                                  <div className="flex flex-wrap gap-1 mt-0.5">
                                    {token.discovery_methods.map(m => (
                                      <span key={m} className="px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400 text-[10px]">{m}</span>
                                    ))}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Subreddits</span>
                                  <div className="flex flex-wrap gap-1 mt-0.5">
                                    {token.source_names.slice(0, 3).map(s => (
                                      <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-[#1e1e2e] text-[#a1a1aa]">
                                        {s}
                                      </span>
                                    ))}
                                    {token.source_names.length > 3 && (
                                      <span className="text-[10px] text-[#52525b]">+{token.source_names.length - 3}</span>
                                    )}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">KPIs</span>
                                  <div className="text-[#a1a1aa] mt-0.5 font-mono text-[11px]">
                                    {token.mention_count} mentions · {token.unique_user_count} users<br />
                                    {token.post_count} posts · {token.comment_count} comments<br />
                                    {token.subreddit_count} subreddits · {token.upvotes} upvotes
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Last Seen</span>
                                  <div className="text-[#a1a1aa] mt-0.5">
                                    {new Date(token.last_seen_in_window).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                  </div>
                                </div>
                                <div>
                                  <span className="text-[#52525b]">Total Score</span>
                                  <div className="text-[#a1a1aa] mt-0.5 font-mono">{token.total_score}</div>
                                </div>
                                {token.dex_url && (
                                  <div className="col-span-2">
                                    <span className="text-[#52525b]">DEX Link</span>
                                    <a
                                      href={token.dex_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="flex items-center gap-1 text-orange-400 hover:text-orange-300 mt-0.5 truncate"
                                      onClick={e => e.stopPropagation()}
                                    >
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
    <div className={`${bg} border border-[#1e1e2e] rounded-xl p-4 transition-all ${loading ? 'border-orange-500/30 shadow-[0_0_12px_rgba(249,115,22,0.1)]' : ''}`}>
      <div className="flex items-center gap-2 mb-1">
        <Icon size={14} className={loading ? 'text-orange-400 animate-pulse' : color} />
        <span className="text-xs text-[#71717a]">{label}</span>
      </div>
      <div className={`text-2xl font-bold ${loading ? 'text-orange-400' : color}`}>
        {loading && sub === undefined ? (
          <span className="inline-flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-orange-400 animate-pulse" />
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
        className="bg-[#1a1a24] border border-[#1e1e2e] rounded-md px-2 py-1 text-xs text-[#e4e4e7] focus:outline-none focus:border-orange-500/50"
      >
        {options.map(o => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}
