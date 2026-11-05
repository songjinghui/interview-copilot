import { useEffect, useState } from "react";
import type { ApiError, ApiPort, Page } from "./types";
export function useQuery<T>(api: ApiPort, path: string, revision = 0) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState<ApiError | null>(null),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true,
      timer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    setError(null);
    setData(null);
    async function fetchData(attempt = 0) {
      try {
        const value = await api.query<T>(path);
        if (active) {
          setData(value);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if (!active) return;
        const failure = e as ApiError;
        setError(
          failure.code ? failure : { message: "服务连接中断，正在重新连接…" },
        );
        setLoading(false);
        if (
          !failure.code ||
          failure.code === "STORAGE_ERROR" ||
          failure.code === "BUSY"
        )
          timer = setTimeout(
            () => void fetchData(attempt + 1),
            [1000, 2000, 5000, 10000][Math.min(attempt, 3)],
          );
      }
    }
    void fetchData();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, path, revision]);
  return { data, error, loading };
}
export async function allPages<T>(api: ApiPort, path: string) {
  let cursor: string | null = null;
  const items: T[] = [];
  do {
    const page: Page<T> = await api.query<Page<T>>(
      path +
        (path.includes("?") ? "&" : "?") +
        "limit=100" +
        (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
    );
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return items;
}
