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
  latest_runs: { layer_name: string; tokens_processed: number; tokens_passed: number; tokens_rejected: number }[];
  tokens_in_pipeline: number;
  tokens_by_status: Record<string, number>;
  progress?: {
    step: number;
    layer: string;
    status: string;
    detail: string;
    updated_at?: string;
    sub_layers?: { name: string; count: number; status: string }[];
  };
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
  triggerPipeline: () => fetchJSON<{ status: string; message: string }>('/pipeline/run', { method: 'POST' }),
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
  first_seen_in_window: string;
  last_seen_in_window: string;
  discovery_methods: string[];
  source_names: string[];
  dex_url: string | null;
  pair_address: string | null;
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
  getDiscovery: (params?: { window?: string; limit?: number; min_mentions?: number; min_users?: number }) => {
    const sp = new URLSearchParams();
    if (params?.window) sp.set('window', params.window);
    if (params?.limit) sp.set('limit', String(params.limit));
    if (params?.min_mentions) sp.set('min_mentions', String(params.min_mentions));
    if (params?.min_users) sp.set('min_users', String(params.min_users));
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
