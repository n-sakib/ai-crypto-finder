// DexScreener Discovery Types
export interface DexScreenerDiscoveryToken {
  rank: number;
  chain: string;
  token_address: string;
  symbol: string | null;
  name: string | null;
  score: number;
  pair_address: string | null;
  dex_url: string | null;
  dex_id: string | null;
  price_usd: number | null;
  price_change_5m: number | null;
  price_change_1h: number | null;
  price_change_6h: number | null;
  price_change_24h: number | null;
  volume_5m: number | null;
  volume_1h: number | null;
  volume_6h: number | null;
  volume_24h: number | null;
  txns_5m_buys: number | null;
  txns_5m_sells: number | null;
  txns_1h_buys: number | null;
  txns_1h_sells: number | null;
  liquidity_usd: number | null;
  market_cap: number | null;
  fdv: number | null;
  total_boosts: number | null;
  boost_amount: number | null;
  is_boosted: boolean;
  pair_created_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface DexScreenerDiscoveryResponse {
  window: string;
  window_start: string;
  window_end: string;
  total_tokens: number;
  generated_at: string;
  tokens: DexScreenerDiscoveryToken[];
}

export interface DexScreenerStats {
  total_tokens: number;
  boosted_tokens: number;
  latest_token_at: string | null;
  generated_at: string;
}
