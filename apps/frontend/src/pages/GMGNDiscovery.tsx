import React from 'react';
import { RefreshCw, TrendingUp, Users, Zap } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { gmgnApi } from '../api/client';
import type { GMGNDiscoveryToken, GMGNKOLCluster } from '../api/gmgn';

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + '…' : s;
}

const CHAIN_COLORS: Record<string, string> = {
  ethereum: 'bg-blue-500/15 text-blue-400',
  solana: 'bg-gradient-to-r from-purple-500/15 to-cyan-500/15 text-purple-400',
  bsc: 'bg-yellow-500/15 text-yellow-400',
  base: 'bg-blue-600/15 text-blue-300',
};

function formatUSD(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(2)}K`;
  return `$${n.toFixed(2)}`;
}

function formatTimeAgo(value: string | null | undefined): string {
  if (!value) return '—';
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

export default function GMGNDiscovery() {
  const [window, setWindow] = React.useState('1h');
  const [kolWindow, setKolWindow] = React.useState('30m');
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['gmgn-discovery', window],
    queryFn: () => gmgnApi.getDiscovery({ window, limit: 50 }),
    refetchInterval: 60_000,
  });
  const { data: kolData, isLoading: kolLoading, error: kolError } = useQuery({
    queryKey: ['gmgn-kol-clusters', kolWindow],
    queryFn: () => gmgnApi.getKOLClusters({ chain: 'sol', window: kolWindow, limit: 200, min_buyers: 2 }),
    refetchInterval: 60_000,
  });
  const { data: stats } = useQuery({
    queryKey: ['gmgn-stats'],
    queryFn: gmgnApi.getStats,
    refetchInterval: 30_000,
  });
  const [collecting, setCollecting] = React.useState(false);

  const handleCollect = async () => {
    setCollecting(true);
    try {
      await gmgnApi.triggerCollect();
    } catch (error) {
      console.error('GMGN collect failed', error);
    }
    setTimeout(() => { refetch(); setCollecting(false); }, 3000);
  };

  return (
    <div className="px-2 py-3 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-[#e4e4e7] flex items-center gap-2">
            <Zap size={20} className="text-amber-400" />
            GMGN Discovery
          </h1>
          <p className="text-xs text-[#71717a] mt-1">
            {stats?.total_tokens ?? 0} tokens tracked · trending & new pairs from gmgn.ai
          </p>
        </div>
        <button
          onClick={handleCollect}
          disabled={collecting}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium bg-amber-500 text-black hover:bg-amber-400 disabled:opacity-50 transition-all"
        >
          <RefreshCw size={14} className={collecting ? 'animate-spin' : ''} />
          {collecting ? 'Collecting…' : 'Fetch GMGN'}
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Tokens', value: stats?.total_tokens ?? '…' },
          { label: 'Latest', value: stats?.latest_token_at ? new Date(stats.latest_token_at).toLocaleTimeString() : '…' },
          { label: 'Window', value: window },
        ].map(s => (
          <div key={s.label} className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-4">
            <div className="text-[10px] text-[#71717a] uppercase tracking-wider">{s.label}</div>
            <div className="text-lg font-bold text-[#e4e4e7] mt-1 font-mono">{s.value}</div>
          </div>
        ))}
      </div>

      {/* Window selector */}
      <div className="flex gap-2">
        {['15m', '30m', '1h', '6h', '24h'].map(w => (
          <button
            key={w}
            onClick={() => setWindow(w)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              window === w
                ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                : 'bg-[#13131a] text-[#71717a] border border-[#1e1e2e] hover:text-[#a1a1aa]'
            }`}
          >
            {w}
          </button>
        ))}
      </div>

      {/* KOL co-buy clusters */}
      <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
          <h2 className="text-sm font-semibold flex items-center gap-2 text-[#e4e4e7]">
            <Users size={14} className="text-cyan-400" />
            KOL Co-Buys
            <span className="text-xs text-[#71717a] font-normal">
              {kolData?.clusters.length ?? 0} coins
            </span>
          </h2>
          <div className="flex flex-wrap gap-2">
            {['15m', '30m', '1h', '6h'].map(w => (
              <button
                key={w}
                onClick={() => setKolWindow(w)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  kolWindow === w
                    ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30'
                    : 'bg-[#0f0f16] text-[#71717a] border border-[#1e1e2e] hover:text-[#a1a1aa]'
                }`}
              >
                {w}
              </button>
            ))}
          </div>
        </div>

        {kolLoading ? (
          <div className="flex items-center gap-2 text-sm text-[#71717a] py-8 justify-center">
            <RefreshCw size={14} className="animate-spin" /> Loading KOL buys…
          </div>
        ) : kolError ? (
          <div className="text-sm text-red-300 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
            {kolError instanceof Error ? kolError.message : 'Could not load GMGN KOL buys'}
          </div>
        ) : !kolData?.clusters.length ? (
          <div className="text-center py-10 text-[#71717a] text-sm">
            No coins were bought by 2 or more KOL wallets in the selected window.
          </div>
        ) : (
          <div className="space-y-2">
            {kolData.clusters.map((cluster: GMGNKOLCluster) => (
              <div
                key={cluster.token_address}
                className="grid grid-cols-1 gap-3 rounded-lg border border-[#1e1e2e] bg-[#0f0f16] p-3 lg:grid-cols-[minmax(0,1.4fr)_110px_120px_minmax(0,1.7fr)] lg:items-center"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 min-w-0">
                    {cluster.logo && (
                      <img src={cluster.logo} alt="" className="h-7 w-7 rounded-full bg-[#1e1e2e] shrink-0" />
                    )}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-semibold text-[#e4e4e7] truncate">
                          {cluster.name || cluster.symbol || 'Unknown'}
                        </span>
                        {cluster.symbol && (
                          <span className="text-xs text-[#71717a] shrink-0">${truncate(cluster.symbol, 10)}</span>
                        )}
                      </div>
                      <div className="text-[10px] text-[#52525b] font-mono truncate">{cluster.token_address}</div>
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 text-xs lg:block lg:space-y-1">
                  <div>
                    <div className="text-[#71717a]">KOLs</div>
                    <div className="font-mono text-cyan-300 font-semibold">{cluster.kol_count}</div>
                  </div>
                  <div>
                    <div className="text-[#71717a]">Buys</div>
                    <div className="font-mono text-[#e4e4e7]">{cluster.buy_count}</div>
                  </div>
                  <div>
                    <div className="text-[#71717a]">Last</div>
                    <div className="font-mono text-[#a1a1aa]">{formatTimeAgo(cluster.last_buy_at)}</div>
                  </div>
                </div>

                <div className="text-xs">
                  <div className="text-[#71717a]">Buy USD</div>
                  <div className="font-mono text-[#e4e4e7] font-semibold">{formatUSD(cluster.total_amount_usd)}</div>
                </div>

                <div className="min-w-0">
                  <div className="text-xs text-[#71717a] mb-1">KOL wallets</div>
                  <div className="flex flex-wrap gap-1.5">
                    {cluster.kol_wallets.slice(0, 6).map(wallet => (
                      <span
                        key={wallet.maker}
                        className="max-w-full rounded border border-[#27273a] bg-[#181824] px-2 py-1 text-xs text-[#d4d4d8]"
                        title={`${wallet.maker} · ${formatUSD(wallet.amount_usd)}`}
                      >
                        {truncate(wallet.twitter_username || wallet.twitter_name || wallet.maker, 18)}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Token Table */}
      <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
        <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
          <TrendingUp size={14} className="text-amber-400" />
          Trending Tokens ({window})
          <span className="text-xs text-[#71717a] ml-auto">{data?.total_tokens ?? 0} tokens</span>
        </h2>

        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[#71717a] py-8 justify-center">
            <RefreshCw size={14} className="animate-spin" /> Loading…
          </div>
        ) : !data?.tokens?.length ? (
          <div className="text-center py-12 text-[#71717a] text-sm">
            No tokens yet. Click "Fetch GMGN" to collect.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[#71717a] border-b border-[#1e1e2e]">
                  <th className="text-left py-2 px-2 w-8">#</th>
                  <th className="text-left py-2 px-2">Token</th>
                  <th className="text-right py-2 px-2">Score</th>
                  <th className="text-right py-2 px-2">Price</th>
                  <th className="text-right py-2 px-2">5m</th>
                  <th className="text-right py-2 px-2">24h</th>
                  <th className="text-right py-2 px-2 hidden md:table-cell">Volume</th>
                  <th className="text-right py-2 px-2 hidden md:table-cell">Swaps</th>
                  <th className="text-right py-2 px-2 hidden lg:table-cell">MCap</th>
                </tr>
              </thead>
              <tbody>
                {data.tokens.map((token: GMGNDiscoveryToken) => (
                  <tr key={token.token_address} className="border-b border-[#1a1a24] hover:bg-[#1a1a24] transition-colors">
                    <td className="py-2.5 px-2 text-[#71717a] text-xs font-mono">{token.rank}</td>
                    <td className="py-2.5 px-2">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${CHAIN_COLORS[token.chain] || 'bg-zinc-500/15 text-zinc-400'}`}>
                          {token.chain}
                        </span>
                        <span className="font-medium text-[#e4e4e7]">{token.name || token.symbol || 'Unknown'}</span>
                        {token.symbol && <span className="text-xs text-[#71717a]">${token.symbol}</span>}
                        {token.hot_level != null && (
                          <span className="text-[10px] px-1 py-0.5 rounded bg-red-500/15 text-red-400">
                            Hot {token.hot_level}
                          </span>
                        )}
                      </div>
                      <div className="text-[10px] text-[#52525b] font-mono mt-0.5">{token.token_address}</div>
                    </td>
                    <td className="py-2.5 px-2 text-right">
                      <span className="font-mono text-[#e4e4e7] font-medium">{token.score.toFixed(0)}</span>
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-xs text-[#a1a1aa]">
                      {token.price_usd != null ? `$${token.price_usd.toFixed(6)}` : '—'}
                    </td>
                    <td className={`py-2.5 px-2 text-right font-mono text-xs ${(token.price_change_5m ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {token.price_change_5m != null ? `${token.price_change_5m >= 0 ? '+' : ''}${token.price_change_5m.toFixed(1)}%` : '—'}
                    </td>
                    <td className={`py-2.5 px-2 text-right font-mono text-xs ${(token.price_change_24h ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {token.price_change_24h != null ? `${token.price_change_24h >= 0 ? '+' : ''}${token.price_change_24h.toFixed(1)}%` : '—'}
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-xs text-[#a1a1aa] hidden md:table-cell">
                      {formatUSD(token.volume_24h)}
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-xs text-[#a1a1aa] hidden md:table-cell">
                      {token.swaps_24h ?? '—'}
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-xs text-[#a1a1aa] hidden lg:table-cell">
                      {formatUSD(token.market_cap)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
