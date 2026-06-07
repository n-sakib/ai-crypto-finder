import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, telegramApi, redditApi, twitterApi } from '../api/client';
import type { TokenSummary, TokenDetail, RankingResponse, PipelineStatusData, PipelineResultsResponse, SystemStats, TelegramDiscoveryResponse, TelegramSource, TelegramStats, RedditDiscoveryResponse, RedditSource, RedditStats, TwitterDiscoveryResponse, TwitterSource, TwitterStats } from '../api/client';

export function useRankings() {
  return useQuery<RankingResponse>({
    queryKey: ['rankings'],
    queryFn: api.getRankings,
    refetchInterval: 30_000,
  });
}

export function useTokens(tier?: string) {
  return useQuery<TokenSummary[]>({
    queryKey: ['tokens', tier],
    queryFn: () => api.getTokens({ tier, limit: 100 }),
    refetchInterval: 30_000,
  });
}

export function useToken(id: string) {
  return useQuery<TokenDetail>({
    queryKey: ['token', id],
    queryFn: () => api.getToken(id),
    enabled: !!id,
  });
}

export function usePipelineStatus() {
  return useQuery<PipelineStatusData>({
    queryKey: ['pipeline-status'],
    queryFn: api.getPipelineStatus,
    refetchInterval: 15_000,
  });
}

export function useStats() {
  return useQuery<SystemStats>({
    queryKey: ['stats'],
    queryFn: api.getStats,
    refetchInterval: 30_000,
  });
}

export function useTriggerPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (window?: string) => api.triggerPipeline(window),
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['pipeline-status'] });
        qc.invalidateQueries({ queryKey: ['pipeline-results'] });
        qc.invalidateQueries({ queryKey: ['rankings'] });
        qc.invalidateQueries({ queryKey: ['tokens'] });
        qc.invalidateQueries({ queryKey: ['stats'] });
      }, 5000);
    },
  });
}

export function usePipelineResults(params?: { limit?: number; offset?: number }) {
  return useQuery<PipelineResultsResponse>({
    queryKey: ['pipeline-results', params],
    queryFn: () => api.getPipelineResults(params),
    refetchInterval: 30_000,
  });
}

// ── Telegram Discovery Hooks ─────────────────────────────────────────

export function useTelegramDiscovery(params?: { window?: string; limit?: number; min_mentions?: number; min_groups?: number; min_unique_users?: number }) {
  return useQuery<TelegramDiscoveryResponse>({
    queryKey: ['telegram-discovery', params],
    queryFn: () => telegramApi.getDiscovery(params),
    refetchInterval: 30_000,
    staleTime: 0,
  });
}

export function useTelegramSources() {
  return useQuery<TelegramSource[]>({
    queryKey: ['telegram-sources'],
    queryFn: telegramApi.getSources,
    refetchInterval: 30_000,
    staleTime: 0,
  });
}

export function useTelegramStats() {
  return useQuery<TelegramStats>({
    queryKey: ['telegram-stats'],
    queryFn: telegramApi.getStats,
    refetchInterval: 15_000,
    staleTime: 0,
  });
}

export function useTriggerTelegramCollect() {
  return useMutation({
    mutationFn: telegramApi.triggerCollect,
  });
}

// ── Reddit Discovery Hooks ───────────────────────────────────────────

export function useRedditDiscovery(params?: { window?: string; limit?: number; min_mentions?: number; min_users?: number }) {
  return useQuery<RedditDiscoveryResponse>({
    queryKey: ['reddit-discovery', params],
    queryFn: () => redditApi.getDiscovery(params),
    refetchInterval: 60_000,
    staleTime: 0,
  });
}

export function useRedditSources() {
  return useQuery<RedditSource[]>({
    queryKey: ['reddit-sources'],
    queryFn: redditApi.getSources,
    refetchInterval: 60_000,
    staleTime: 0,
  });
}

export function useRedditStats() {
  return useQuery<RedditStats>({
    queryKey: ['reddit-stats'],
    queryFn: redditApi.getStats,
    refetchInterval: 30_000,
    staleTime: 0,
  });
}

// ── Twitter Discovery Hooks ──────────────────────────────────────────

export function useTwitterDiscovery(params?: { window?: string; limit?: number; min_mentions?: number; min_users?: number }) {
  return useQuery<TwitterDiscoveryResponse>({
    queryKey: ['twitter-discovery', params],
    queryFn: () => twitterApi.getDiscovery(params),
    refetchInterval: 60_000,
    staleTime: 0,
  });
}

export function useTwitterSources() {
  return useQuery<TwitterSource[]>({
    queryKey: ['twitter-sources'],
    queryFn: twitterApi.getSources,
    refetchInterval: 60_000,
    staleTime: 0,
  });
}

export function useTwitterStats() {
  return useQuery<TwitterStats>({
    queryKey: ['twitter-stats'],
    queryFn: twitterApi.getStats,
    refetchInterval: 30_000,
    staleTime: 0,
  });
}
