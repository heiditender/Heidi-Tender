"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PaginatedQuery } from "@/lib/api";

export interface PaginatedListState<T> {
  rows: T[];
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  hasMore: boolean;
  empty: boolean;
  reload: () => Promise<void>;
  loadMore: () => Promise<void>;
}

interface UsePaginatedListParams<T, Q extends object> {
  query: Q;
  pageSize: number;
  fetchPage: (query: Q & PaginatedQuery) => Promise<T[]>;
}

function stringifyQuery(query: object): string {
  const entries = Object.entries(query as Record<string, unknown>)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify(entries);
}

export function usePaginatedList<T, Q extends object>({
  query,
  pageSize,
  fetchPage,
}: UsePaginatedListParams<T, Q>): PaginatedListState<T> {
  const [rows, setRows] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const requestIdRef = useRef(0);

  const queryKey = useMemo(() => stringifyQuery(query), [query]);

  const reload = useCallback(async () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    setError(null);
    try {
      const nextRows = await fetchPage({ ...(query as object), limit: pageSize, offset: 0 } as Q & PaginatedQuery);
      if (requestId !== requestIdRef.current) {
        return;
      }
      setRows(nextRows);
      setHasMore(nextRows.length >= pageSize);
    } catch (err) {
      if (requestId !== requestIdRef.current) {
        return;
      }
      setRows([]);
      setHasMore(false);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [fetchPage, pageSize, query]);

  const loadMore = useCallback(async () => {
    if (loading || loadingMore || !hasMore) {
      return;
    }
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoadingMore(true);
    setError(null);
    try {
      const nextRows = await fetchPage(
        { ...(query as object), limit: pageSize, offset: rows.length } as Q & PaginatedQuery
      );
      if (requestId !== requestIdRef.current) {
        return;
      }
      setRows((prev) => [...prev, ...nextRows]);
      setHasMore(nextRows.length >= pageSize);
    } catch (err) {
      if (requestId !== requestIdRef.current) {
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestId === requestIdRef.current) {
        setLoadingMore(false);
      }
    }
  }, [fetchPage, hasMore, loading, loadingMore, pageSize, query, rows.length]);

  useEffect(() => {
    void reload();
  }, [queryKey, reload]);

  return {
    rows,
    loading,
    loadingMore,
    error,
    hasMore,
    empty: !loading && rows.length === 0,
    reload,
    loadMore,
  };
}
