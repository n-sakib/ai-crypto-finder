import { Link } from 'react-router-dom';
import { ChevronRight, TrendingUp, TrendingDown } from 'lucide-react';
import TierBadge from './TierBadge';
import type { TokenSummary } from '../api/client';

export default function TokenRow({ token }: { token: TokenSummary }) {
  const up = token.price_change_24h >= 0;
  return (
    <Link to={`/token/${token.id}`} className="bg-[#13131a] border border-[#1e1e2e] rounded-lg px-4 py-3 flex items-center gap-4 no-underline hover:border-indigo-500/30 transition-all group">
      <div className="w-8 text-center">
        {token.rank_position ? <span className="text-sm font-bold text-[#71717a]">#{token.rank_position}</span> : <span className="text-sm text-[#71717a]">—</span>}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-bold text-sm text-[#e4e4e7]">{token.symbol}</span>
          <TierBadge tier={token.tier} risk={token.risk_level} />
        </div>
        <div className="text-xs mt-0.5 truncate text-[#71717a]">{token.name || token.contract_address.slice(0,8)} · {token.chain}</div>
      </div>
      <div className="text-right">
        <div className="flex items-center gap-1 justify-end text-sm font-semibold">
          {up ? <TrendingUp size={14} color="#22c55e" /> : <TrendingDown size={14} color="#ef4444" />}
          <span className={up ? 'text-green-500' : 'text-red-500'}>{up ? '+' : ''}{token.price_change_24h.toFixed(1)}%</span>
        </div>
        <div className="text-xs mt-0.5 text-[#71717a]">${(token.liquidity_usd/1000).toFixed(0)}k liq · ${(token.volume_24h/1000).toFixed(0)}k vol</div>
      </div>
      <ChevronRight size={16} className="opacity-0 group-hover:opacity-100 transition-opacity text-[#71717a]" />
    </Link>
  );
}
