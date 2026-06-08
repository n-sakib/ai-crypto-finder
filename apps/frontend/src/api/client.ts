const API_BASE = '/api/v1';

export interface TokenSummary {
  id: string;
  chain: string;
  symbol: string;
  name: string | null;
  contract_address: string;
  pair_address: string;
  age_bucket: string | null;
  liquidity_usd: number;
  volume_24h: number;
  price_change_24h: number;
  market_cap: number;
  early_momentum_score: number;
  risk_level: string | null;
  tier: string | null;
  rank_position: number | null;
}

export interface TokenDetail extends TokenSummary {
  dex_id: string | null;
  launched_at: string | null;
  first_seen_at: string | null;
  pipeline_status: string;
  is_honeypot: boolean;
  has_mint_risk: boolean;
  has_sell_block: boolean;
  is_liquidity_locked: boolean;
  buy_tax_pct: number;
  sell_tax_pct: number;
  liquidity_trend: string | null;
  volume_1h: number;
  trade_count_24h: number;
  unique_buyers_24h: number;
  unique_sellers_24h: number;
  holder_count: number;
  meaningful_holders: number;
  top_holder_pct: number;
  price_usd: number;
  price_change_1h: number;
  price_change_6h: number;
  price_change_7d: number;
  distance_from_24h_high: number;
  distance_from_7d_high: number;
  distance_from_30d_high: number;
  attention_score: number;
  market_flow_score: number;
  adoption_score: number;
  liquidity_quality_score: number;
  smart_money_score: number;
  narrative_score: number;
  price_compression_score: number;
  risk_score: number;
  is_approved: boolean;
  coingecko_trending: boolean;
  cmc_trending: boolean;
  news_mentions: number;
}

export interface RankingResponse {
  tier_a: TokenSummary[];
  tier_b: TokenSummary[];
  tier_c: TokenSummary[];
  excluded: TokenSummary[];
  total_candidates: number;
  generated_at: string;
}

export interface PipelineStatusData {
  status: string;
  step: string;
  detail: string;
  tokens: number;
  total: number;
}

// Unified pipeline types
export interface UnifiedWindowData {
  price?: number;
  price_change?: number;
  volume?: number;
  buys?: number;
  sells?: number;
  trades?: number;
  liquidity?: number;
  market_cap?: number;
  telegram?: {
    mentions: number;
    users: number;
    groups: number;
    reactions: number;
    replies: number;
  };
}

export interface UnifiedTokenData {
  rank: number;
  chain: string;
  token_address: string;
  symbol: string | null;
  name: string | null;
  composite_score: number;
  source_groups: string[];
  group_count: number;
  discovery_methods: string[];
  dex_url?: string;
  pair_address?: string;
  dex_id?: string;
  gmgn_score?: number;
  gmgn_hot_level?: number;
  is_dexscreener_trending?: boolean;
  is_dexscreener_boosted?: boolean;
  is_gmgn_trending?: boolean;
  dexscreener_trending_rank?: number | null;
  dexscreener_boost_amount?: number | null;
  dexscreener_boost_total?: number | null;
  gmgn_trending_rank?: number | null;
  windows: {
    '5m'?: UnifiedWindowData;
    '1h'?: UnifiedWindowData;
    '6h'?: UnifiedWindowData;
    '24h'?: UnifiedWindowData;
  };
}

export interface PipelineResultsResponse {
  total: number;
  pipeline_status: PipelineStatusData;
  tokens: UnifiedTokenData[];
}

export interface SystemStats {
  total_tokens_tracked: number;
  tokens_in_pipeline: number;
  tokens_ranked: number;
  tier_a_count: number;
  tier_b_count: number;
  tier_c_count: number;
  excluded_count: number;
}

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return res.json();
}

export const api = {
  getRankings: () => fetchJSON<RankingResponse>('/rankings'),
  getTokens: (params?: { tier?: string; chain?: string; min_momentum?: number; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.tier) sp.set('tier', params.tier);
    if (params?.chain) sp.set('chain', params.chain);
    if (params?.min_momentum) sp.set('min_momentum', String(params.min_momentum));
    if (params?.limit) sp.set('limit', String(params.limit));
    const qs = sp.toString();
    return fetchJSON<TokenSummary[]>(`/tokens${qs ? `?${qs}` : ''}`);
  },
  getToken: (id: string) => fetchJSON<TokenDetail>(`/tokens/${id}`),
  getPipelineStatus: () => fetchJSON<PipelineStatusData>('/pipeline/status'),
  getPipelineResults: (params?: { limit?: number; offset?: number }) => {
    const sp = new URLSearchParams();
    if (params?.limit) sp.set('limit', String(params.limit));
    if (params?.offset) sp.set('offset', String(params.offset));
    const qs = sp.toString();
    return fetchJSON<PipelineResultsResponse>(`/pipeline/results${qs ? `?${qs}` : ''}`);
  },
  triggerPipeline: (window?: string) => {
    const qs = window ? `?window=${window}` : '';
    return fetchJSON<{ status: string }>(`/pipeline/run${qs}`, { method: 'POST' });
  },
  clearPipelineResults: () =>
    fetchJSON<{ status: string; deleted: number }>('/pipeline/results', { method: 'DELETE' }),
  getStats: () => fetchJSON<SystemStats>('/stats'),
};

// ── Telegram Discovery Types ─────────────────────────────────────────

export interface TelegramSource {
  id: string;
  source_id: string;
  name: string;
  telegram_identifier: string;
  source_type: string;
  enabled: boolean;
  last_message_id: number | null;
  last_collected_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TelegramDiscoveryToken {
  rank: number;
  chain: string;
  token_address: string;
  symbol: string;
  name: string | null;
  mention_count: number;
  unique_user_count: number;
  group_count: number;
  total_reactions: number;
  total_replies: number;
  total_views: number;
  total_forwards: number;
  first_seen_in_window: string;
  last_seen_in_window: string;
  discovery_methods: string[];
  source_names: string[];
  source_mentions: Record<string, number>;
  dex_url: string | null;
  pair_address: string | null;
  ai_decision: string | null;
  ai_confidence: number | null;
  ai_reasoning: string | null;
  ai_red_flags: string[];
  ai_positive_signals: string[];
}

export interface TelegramDiscoveryResponse {
  window: string;
  window_start: string;
  window_end: string;
  total_tokens: number;
  total_messages: number;
  generated_at: string;
  tokens: TelegramDiscoveryToken[];
}

export interface TelegramStats {
  candidate_tokens: number;
  total_mentions: number;
  messages_stored: number;
  enabled_sources: number;
  latest_mention_at: string | null;
  generated_at: string;
}

export const telegramApi = {
  getDiscovery: (params?: { window?: string; limit?: number; min_mentions?: number; min_groups?: number; min_unique_users?: number }) => {
    const sp = new URLSearchParams();
    if (params?.window) sp.set('window', params.window);
    if (params?.limit) sp.set('limit', String(params.limit));
    if (params?.min_mentions) sp.set('min_mentions', String(params.min_mentions));
    if (params?.min_groups) sp.set('min_groups', String(params.min_groups));
    if (params?.min_unique_users) sp.set('min_unique_users', String(params.min_unique_users));
    const qs = sp.toString();
    return fetchJSON<TelegramDiscoveryResponse>(`/telegram/discovery${qs ? `?${qs}` : ''}`);
  },
  getSources: () => fetchJSON<TelegramSource[]>('/telegram/sources'),
  getStats: () => fetchJSON<TelegramStats>('/telegram/discovery/stats'),
  triggerCollect: () => fetchJSON<{ status: string; message: string }>('/telegram/collect', { method: 'POST' }),
  getCollectStatus: () => fetchJSON<{
    status: string; group: string; total_messages: number;
    total_tokens: number; total_mentions?: number;
    sources_done: number; sources_total: number;
    error?: string;
  }>('/telegram/collect/status'),
  reset: () => fetchJSON<{ status: string; message: string; remaining: Record<string, number> }>('/telegram/reset', { method: 'POST', signal: AbortSignal.timeout(10000) }),
  addSource: (identifier: string, name?: string) => {
    const sp = new URLSearchParams();
    sp.set('telegram_identifier', identifier);
    if (name) sp.set('name', name);
    return fetchJSON<TelegramSource>(`/telegram/sources?${sp}`, { method: 'POST' });
  },
  removeSource: (sourceId: string) => fetchJSON<{ status: string }>(`/telegram/sources/${sourceId}`, { method: 'DELETE' }),
  toggleSource: (sourceId: string) => fetchJSON<{ status: string; enabled: boolean }>(`/telegram/sources/${sourceId}/toggle`, { method: 'PUT' }),
};

// ── Reddit Discovery Types ───────────────────────────────────────────

export interface RedditSource {
  id: string;
  source_id: string;
  name: string;
  subreddit_name: string;
  source_type: string;
  enabled: boolean;
  last_post_id: string | null;
  last_collected_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RedditDiscoveryToken {
  rank: number;
  chain: string;
  token_address: string;
  symbol: string;
  name: string | null;
  mention_count: number;
  unique_user_count: number;
  subreddit_count: number;
  post_count: number;
  total_score: number;
  first_seen_in_window: string;
  last_seen_in_window: string;
  discovery_methods: string[];
  source_names: string[];
  dex_url: string | null;
  pair_address: string | null;
}

export interface RedditDiscoveryResponse {
  window: string;
  window_start: string;
  window_end: string;
  total_tokens: number;
  total_posts: number;
  generated_at: string;
  tokens: RedditDiscoveryToken[];
}

export interface RedditStats {
  candidate_tokens: number;
  total_mentions: number;
  posts_stored: number;
  enabled_sources: number;
  latest_mention_at: string | null;
  generated_at: string;
}

export const redditApi = {
  getDiscovery: (params?: { window?: string; limit?: number; min_mentions?: number; min_users?: number }) => {
    const sp = new URLSearchParams();
    if (params?.window) sp.set('window', params.window);
    if (params?.limit) sp.set('limit', String(params.limit));
    if (params?.min_mentions) sp.set('min_mentions', String(params.min_mentions));
    if (params?.min_users) sp.set('min_users', String(params.min_users));
    const qs = sp.toString();
    return fetchJSON<RedditDiscoveryResponse>(`/reddit/discovery${qs ? `?${qs}` : ''}`);
  },
  getSources: () => fetchJSON<RedditSource[]>('/reddit/sources'),
  getStats: () => fetchJSON<RedditStats>('/reddit/discovery/stats'),
  triggerCollect: () => fetchJSON<{ status: string; message: string }>('/reddit/collect', { method: 'POST' }),
  addSource: (subredditName: string, name?: string, sourceType?: string) => {
    const sp = new URLSearchParams();
    sp.set('subreddit_name', subredditName);
    if (name) sp.set('name', name);
    if (sourceType) sp.set('source_type', sourceType);
    return fetchJSON<RedditSource>(`/reddit/sources?${sp}`, { method: 'POST' });
  },
  removeSource: (sourceId: string) => fetchJSON<{ status: string }>(`/reddit/sources/${sourceId}`, { method: 'DELETE' }),
  toggleSource: (sourceId: string) => fetchJSON<{ status: string; enabled: boolean }>(`/reddit/sources/${sourceId}/toggle`, { method: 'PUT' }),
};

// ── Twitter Discovery Types ──────────────────────────────────────────

export interface TwitterSource {
  id: string;
  source_id: string;
  name: string;
  query: string;
  source_type: string;
  enabled: boolean;
  last_tweet_id: string | null;
  last_collected_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TwitterDiscoveryToken {
  rank: number;
  chain: string;
  token_address: string;
  symbol: string;
  name: string | null;
  mention_count: number;
  unique_user_count: number;
  total_engagement: number;
  authority_mentions: number;
  total_score: number;
  first_seen_in_window: string;
  last_seen_in_window: string;
  discovery_methods: string[];
  source_names: string[];
  dex_url: string | null;
  pair_address: string | null;
}

export interface TwitterDiscoveryResponse {
  window: string;
  window_start: string;
  window_end: string;
  total_tokens: number;
  total_tweets: number;
  generated_at: string;
  tokens: TwitterDiscoveryToken[];
}

export interface TwitterStats {
  candidate_tokens: number;
  total_mentions: number;
  tweets_stored: number;
  enabled_sources: number;
  latest_mention_at: string | null;
  generated_at: string;
}

export const twitterApi = {
  getStatus: () => fetchJSON<{ configured: boolean; message: string }>('/twitter/discovery/status'),
  getDiscovery: (params?: { window?: string; limit?: number; min_mentions?: number; min_users?: number }) => {
    const sp = new URLSearchParams();
    if (params?.window) sp.set('window', params.window);
    if (params?.limit) sp.set('limit', String(params.limit));
    if (params?.min_mentions) sp.set('min_mentions', String(params.min_mentions));
    if (params?.min_users) sp.set('min_users', String(params.min_users));
    const qs = sp.toString();
    return fetchJSON<TwitterDiscoveryResponse>(`/twitter/discovery${qs ? `?${qs}` : ''}`);
  },
  getSources: () => fetchJSON<TwitterSource[]>('/twitter/sources'),
  getStats: () => fetchJSON<TwitterStats>('/twitter/discovery/stats'),
  triggerCollect: () => fetchJSON<{ status: string; message: string }>('/twitter/collect', { method: 'POST' }),
  addSource: (query: string, name?: string, sourceType?: string) => {
    const sp = new URLSearchParams();
    sp.set('query', query);
    if (name) sp.set('name', name);
    if (sourceType) sp.set('source_type', sourceType);
    return fetchJSON<TwitterSource>(`/twitter/sources?${sp}`, { method: 'POST' });
  },
  removeSource: (sourceId: string) => fetchJSON<{ status: string }>(`/twitter/sources/${sourceId}`, { method: 'DELETE' }),
  toggleSource: (sourceId: string) => fetchJSON<{ status: string; enabled: boolean }>(`/twitter/sources/${sourceId}/toggle`, { method: 'PUT' }),
};

// ── GMGN API ─────────────────────────────────────────────────────────
import type { GMGNDiscoveryResponse, GMGNStats } from './gmgn';

export const gmgnApi = {
  getDiscovery: (params?: { window?: string; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.window) sp.set('window', params.window);
    if (params?.limit) sp.set('limit', String(params.limit));
    return fetchJSON<GMGNDiscoveryResponse>(`/gmgn/discovery${sp.toString() ? `?${sp}` : ''}`);
  },
  getStats: () => fetchJSON<GMGNStats>('/gmgn/discovery/stats'),
  triggerCollect: () => fetchJSON<{ status: string }>('/gmgn/collect', { method: 'POST' }),
};

// ── DexScreener API ──────────────────────────────────────────────────
import type { DexScreenerDiscoveryResponse, DexScreenerStats } from './dexscreener';

export const dexscreenerApi = {
  getDiscovery: (params?: { window?: string; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.window) sp.set('window', params.window);
    if (params?.limit) sp.set('limit', String(params.limit));
    return fetchJSON<DexScreenerDiscoveryResponse>(`/dexscreener/discovery${sp.toString() ? `?${sp}` : ''}`);
  },
  getStats: () => fetchJSON<DexScreenerStats>('/dexscreener/discovery/stats'),
  triggerCollect: () => fetchJSON<{ status: string }>('/dexscreener/collect', { method: 'POST' }),
};
