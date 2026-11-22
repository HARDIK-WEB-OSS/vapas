"use client";

import { useCallback, useEffect, useState } from "react";

import { errorCode } from "@/components/ui";

export type Loaded<T> = {
  data: T | null;
  error: string | null;
  reload: () => Promise<void>;
};

export function useLoad<T>(load: () => Promise<T>): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    try {
      const value = await load();
      setData(value);
      setError(null);
    } catch (problem) {
      setError(errorCode(problem));
    }
  }, [load]);
  useEffect(() => {
    let active = true;
    load()
      .then((value) => {
        if (active) {
          setData(value);
          setError(null);
        }
      })
      .catch((problem: unknown) => {
        if (active) setError(errorCode(problem));
      });
    return () => {
      active = false;
    };
  }, [load]);
  return { data, error, reload };
}

export function hashToken(): string | null {
  const match = /(?:^|[#&])token=([^&]+)/.exec(window.location.hash);
  return match ? decodeURIComponent(match[1]) : null;
}

export function clearHash(): void {
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}
