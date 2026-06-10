import React from 'react';
import { TrendingUp, RefreshCw, Zap, Flame } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { dexscreenerApi } from '../api/client';
import type { DexScreenerDiscoveryToken } from '../api/dexscreener';

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

export default function DexScreenerDiscovery() {
  const [window, setWindow] = React.useState('1h');
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['dexscreener-discovery', window],
    queryFn: () => dexscreenerApi.getDiscovery({ window, limit: 50 }),
    refetchInterval: 60_000,
  });
  const { data: stats } = useQuery({
    queryKey: ['dexscreener-stats'],
    queryFn: dexscreenerApi.getStats,
    refetchInterval: 30_000,
  });
  const [collecting, setCollecting] = React.useState(false);

  const handleCollect = async () => {
    setCollecting(true);
    try { await dexscreenerApi.triggerCollect(); } catch {}
    setTimeout(() => { refetch(); setCollecting(false); }, 3000);
  };

  return (
    <div className="px-2 py-3 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-[#e4e4e7] flex items-center gap-2">
            <Zap size={20} className="text-cyan-400" />
            DexScreener Discovery
          </h1>
          <p className="text-xs text-[#71717a] mt-1">
            {stats?.total_tokens ?? 0} tokens · {stats?.boosted_tokens ?? 0} boosted · boosted tokens & latest pairs
          </p>
        </div>
        <button
          onClick={handleCollect}
          disabled={collecting}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium bg-cyan-500 text-black hover:bg-cyan-400 disabled:opacity-50 transition-all"
        >
          <RefreshCw size={14} className={collecting ? 'animate-spin' : ''} />
          {collecting ? 'Collecting…' : 'Fetch DexScreener'}
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Tokens', value: stats?.total_tokens ?? '…' },
          { label: 'Boosted', value: stats?.boosted_tokens ?? '…' },
          { label: 'Latest', value: stats?.latest_token_at ? new Date(stats.latest_token_at).toLocaleTimeString() : '…' },
          { label: 'Window', value: window },
        ].map(s => (
          <div key={s.label} className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-4">
            <div className="text-[10px] text-[#71717a] uppercase tracking-wider">{s.label}</div>
            <div className="text-lg font-bold text-[#e4e4e7] mt-1 font-mono">{s.value}</div>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        {['15m', '30m', '1h', '6h', '24h'].map(w => (
          <button
            key={w}
            onClick={() => setWindow(w)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              window === w
                ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                : 'bg-[#13131a] text-[#71717a] border border-[#1e1e2e] hover:text-[#a1a1aa]'
            }`}
          >
            {w}
          </button>
        ))}
      </div>

      <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
        <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]">
          <TrendingUp size={14} className="text-cyan-400" />
          Discovered Tokens ({window})
          <span className="text-xs text-[#71717a] ml-auto">{data?.total_tokens ?? 0} tokens</span>
        </h2>

        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[#71717a] py-8 justify-center">
            <RefreshCw size={14} className="animate-spin" /> Loading…
          </div>
        ) : !data?.tokens?.length ? (
          <div className="text-center py-12 text-[#71717a] text-sm">
            No tokens yet. Click "Fetch DexScreener" to collect.
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
                  <th className="text-right py-2 px-2">1h</th>
                  <th className="text-right py-2 px-2">24h</th>
                  <th className="text-right py-2 px-2 hidden md:table-cell">Volume 5m</th>
                  <th className="text-right py-2 px-2 hidden lg:table-cell">Liquidity</th>
                </tr>
              </thead>
              <tbody>
                {data.tokens.map((token: DexScreenerDiscoveryToken) => (
                  <tr key={token.token_address} className="border-b border-[#1a1a24] hover:bg-[#1a1a24] transition-colors">
                    <td className="py-2.5 px-2 text-[#71717a] text-xs font-mono">{token.rank}</td>
                    <td className="py-2.5 px-2">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${CHAIN_COLORS[token.chain] || 'bg-zinc-500/15 text-zinc-400'}`}>
                          {token.chain}
                        </span>
                        <span className="font-medium text-[#e4e4e7]">{token.name || token.symbol || 'Unknown'}</span>
                        {token.symbol && <span className="text-xs text-[#71717a]">${token.symbol}</span>}
                        {token.is_boosted && (
                          <span className="text-[10px] px-1 py-0.5 rounded bg-cyan-500/15 text-cyan-400" title="Token Boost">
                            <Flame size={10} className="inline" /> Boosted
                          </span>
                        )}
                      </div>
                      <div className="text-[10px] text-[#52525b] font-mono mt-0.5">{token.token_address}</div>
                    </td>
                    <td className="py-2.5 px-2 text-right">
                      <span className="font-mono text-[#e4e4e7] font-medium">{token.score.toFixed(0)}</span>
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-xs text-[#a1a1aa]">
                      {token.price_usd != null ? `$${token.price_usd < 0.0001 ? token.price_usd.toExponential(3) : token.price_usd.toFixed(6)}` : '—'}
                    </td>
                    <td className={`py-2.5 px-2 text-right font-mono text-xs ${(token.price_change_5m ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {token.price_change_5m != null ? `${token.price_change_5m >= 0 ? '+' : ''}${token.price_change_5m.toFixed(1)}%` : '—'}
                    </td>
                    <td className={`py-2.5 px-2 text-right font-mono text-xs ${(token.price_change_1h ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {token.price_change_1h != null ? `${token.price_change_1h >= 0 ? '+' : ''}${token.price_change_1h.toFixed(1)}%` : '—'}
                    </td>
                    <td className={`py-2.5 px-2 text-right font-mono text-xs ${(token.price_change_24h ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {token.price_change_24h != null ? `${token.price_change_24h >= 0 ? '+' : ''}${token.price_change_24h.toFixed(1)}%` : '—'}
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-xs text-[#a1a1aa] hidden md:table-cell">
                      {formatUSD(token.volume_5m)}
                    </td>
                    <td className="py-2.5 px-2 text-right font-mono text-xs text-[#a1a1aa] hidden lg:table-cell">
                      {formatUSD(token.liquidity_usd)}
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
