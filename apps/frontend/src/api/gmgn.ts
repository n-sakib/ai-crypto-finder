// GMGN Discovery Types
export interface GMGNDiscoveryToken {
  rank: number;
  chain: string;
  token_address: string;
  symbol: string | null;
  name: string | null;
  score: number;
  volume_24h: number | null;
  price_change_24h: number | null;
  price_change_5m: number | null;
  market_cap: number | null;
  liquidity: number | null;
  holders: number | null;
  swaps_24h: number | null;
  buys_24h: number | null;
  sells_24h: number | null;
  net_volume_24h: number | null;
  gmgn_score: number | null;
  hot_level: number | null;
  dex_url: string | null;
  pair_address: string | null;
  price_usd: number | null;
  fdv: number | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface GMGNDiscoveryResponse {
  window: string;
  window_start: string;
  window_end: string;
  total_tokens: number;
  generated_at: string;
  tokens: GMGNDiscoveryToken[];
}

export interface GMGNStats {
  total_tokens: number;
  latest_token_at: string | null;
  generated_at: string;
}

export interface GMGNKOLWallet {
  maker: string;
  twitter_username: string | null;
  twitter_name: string | null;
  tags: string[];
  amount_usd: number;
  buy_count: number;
  last_buy_at: string;
}

export interface GMGNKOLTrade {
  transaction_hash: string | null;
  maker: string;
  twitter_username: string | null;
  twitter_name: string | null;
  amount_usd: number;
  price_usd: number | null;
  bought_at: string;
}

export interface GMGNKOLCluster {
  token_address: string;
  symbol: string | null;
  name: string | null;
  logo: string | null;
  launchpad: string | null;
  kol_count: number;
  buy_count: number;
  total_amount_usd: number;
  last_buy_at: string;
  kol_wallets: GMGNKOLWallet[];
  trades: GMGNKOLTrade[];
}

export interface GMGNKOLClustersResponse {
  chain: string;
  window: string;
  generated_at: string;
  total_trades: number;
  total_buy_trades: number;
  clusters: GMGNKOLCluster[];
}
