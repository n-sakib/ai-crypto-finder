import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, ExternalLink, Shield, TrendingUp, Activity, Users, CheckCircle, XCircle } from 'lucide-react';
import { useToken } from '../hooks/useApi';
import TierBadge, { ScoreBar, MomentumBadge } from '../components/TierBadge';

function fmtUSD(v: number): string {
  if (v >= 1e9) return `$${(v/1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v/1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v/1e3).toFixed(0)}k`;
  return `$${v.toFixed(0)}`;
}

export default function TokenDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: token, isLoading } = useToken(id!);

  if (isLoading) return <div className="flex items-center justify-center py-20"><Activity size={24} className="animate-spin text-indigo-400"/></div>;
  if (!token) return <div className="max-w-4xl mx-auto px-4 py-20 text-center"><p className="text-lg text-[#e4e4e7]">Token not found</p><Link to="/" className="text-sm mt-2 inline-block text-indigo-400">← Back</Link></div>;

  return (
    <div className="px-2 py-3">
      <Link to="/" className="inline-flex items-center gap-2 text-xs mb-3 no-underline hover:opacity-80 text-[#71717a]"><ArrowLeft size={12}/> Back to Dashboard</Link>

      <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-4 mb-4">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div className="flex items-start gap-4">
            <MomentumBadge score={token.early_momentum_score}/>
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-lg font-bold text-[#e4e4e7]">{token.symbol}</h1>
                <TierBadge tier={token.tier} risk={token.risk_level}/>
                {token.is_approved && <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase bg-green-500/10 text-green-500 border border-green-500/20"><CheckCircle size={12}/> Approved</span>}
              </div>
              <p className="text-sm mt-1 text-[#71717a]">{token.name||'Unknown'}</p>
              <div className="flex items-center gap-3 mt-2 text-xs text-[#71717a]">
                <span>{token.chain}</span>
                <span className="font-mono">{token.contract_address?.slice(0,8)}...{token.contract_address?.slice(-6)}</span>
                <a href={`https://dexscreener.com/${token.chain}/${token.pair_address}`} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-indigo-400 hover:underline">DEXScreener <ExternalLink size={10}/></a>
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-[#e4e4e7]">${token.price_usd<0.01?token.price_usd.toFixed(8):token.price_usd.toFixed(4)}</div>
            <div className={`text-sm font-semibold mt-1 ${token.price_change_24h>=0?'text-green-500':'text-red-500'}`}>{token.price_change_24h>=0?'+':''}{token.price_change_24h.toFixed(2)}% (24h)</div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]"><Activity size={16}/> Score Breakdown</h2>
            <div className="space-y-3">
              <ScoreBar score={token.market_flow_score} label="Market Flow" color="bg-green-500"/>
              <ScoreBar score={token.attention_score} label="Attention" color="bg-indigo-500"/>
              <ScoreBar score={token.adoption_score} label="Adoption" color="bg-yellow-500"/>
              <ScoreBar score={token.liquidity_quality_score} label="Liquidity" color="bg-purple-500"/>
              <ScoreBar score={token.smart_money_score} label="Smart Money" color="bg-pink-500"/>
              <ScoreBar score={token.narrative_score} label="Narrative" color="bg-teal-500"/>
              <ScoreBar score={token.price_compression_score} label="Price Compress" color="bg-orange-500"/>
              <ScoreBar score={token.risk_score} label="Risk (lower=better)" color="bg-red-500"/>
            </div>
          </div>
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]"><TrendingUp size={16}/> Market Data</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[['Liquidity',fmtUSD(token.liquidity_usd)],['24h Vol',fmtUSD(token.volume_24h)],['Market Cap',fmtUSD(token.market_cap)],['24h Trades',token.trade_count_24h.toLocaleString()],['1h',`${token.price_change_1h>=0?'+':''}${token.price_change_1h.toFixed(1)}%`],['6h',`${token.price_change_6h>=0?'+':''}${token.price_change_6h.toFixed(1)}%`],['7d',`${token.price_change_7d>=0?'+':''}${token.price_change_7d.toFixed(1)}%`],['Buyers/Sellers',`${token.unique_buyers_24h}/${token.unique_sellers_24h}`]].map(([l,v])=>(<div key={l}><div className="text-xs text-[#71717a]">{l}</div><div className="text-sm font-semibold mt-0.5 text-[#e4e4e7]">{v}</div></div>))}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]"><Shield size={16}/> Safety</h2>
            <div className="space-y-2">{[
              ['Honeypot',!token.is_honeypot],['Sell Block',!token.has_sell_block],['Mint Risk',!token.has_mint_risk],['LP Locked',token.is_liquidity_locked],['Buy Tax',token.buy_tax_pct<=5,`${token.buy_tax_pct}%`],['Sell Tax',token.sell_tax_pct<=5,`${token.sell_tax_pct}%`]
            ].map(([l,ok,v])=>(<div key={l as string} className="flex items-center justify-between text-xs"><span className="text-[#71717a]">{l}</span><span className="flex items-center gap-1">{v?<span className="text-[#e4e4e7]">{v}</span>:null}{ok?<CheckCircle size={12} color="#22c55e"/>:<XCircle size={12} color="#ef4444"/>}</span></div>))}</div>
          </div>
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]"><Activity size={16}/> Activity</h2>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between"><span className="text-[#71717a]">24h Trades</span><span className="text-[#e4e4e7]">{token.trade_count_24h.toLocaleString()}</span></div>
              <div className="flex justify-between"><span className="text-[#71717a]">Buyers (24h)</span><span className="text-green-500">{token.unique_buyers_24h.toLocaleString()}</span></div>
              <div className="flex justify-between"><span className="text-[#71717a]">Sellers (24h)</span><span className="text-red-500">{token.unique_sellers_24h.toLocaleString()}</span></div>
              {token.holder_count > 0 ? <>
                <div className="flex justify-between"><span className="text-[#71717a]">Total Holders</span><span className="text-[#e4e4e7]">{token.holder_count.toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-[#71717a]">Meaningful</span><span className="text-[#e4e4e7]">{token.meaningful_holders.toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-[#71717a]">Top Holder</span><span className={token.top_holder_pct > 25 ? 'text-red-500' : 'text-[#e4e4e7]'}>{token.top_holder_pct.toFixed(1)}%</span></div>
              </> : <div className="text-[#71717a] text-[11px] italic pt-1">No holder data available</div>}
            </div>
          </div>
          <div className="bg-[#13131a] border border-[#1e1e2e] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2 text-[#e4e4e7]"><CheckCircle size={16}/> Validation</h2>
            <div className="space-y-2 text-xs">{[
              ['CoinGecko',token.coingecko_trending],['CMC',token.cmc_trending],['News',token.news_mentions>0,`${token.news_mentions} mentions`]
            ].map(([l,ok,v])=>(<div key={l as string} className="flex justify-between"><span className="text-[#71717a]">{l}</span><span className="flex items-center gap-1">{typeof v==='string'?<span className="text-[#e4e4e7]">{v}</span>:null}{ok?<CheckCircle size={12} color="#22c55e"/>:<XCircle size={12} color="var(--color-text-muted)"/>}</span></div>))}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
