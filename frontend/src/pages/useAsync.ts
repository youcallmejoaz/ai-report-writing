import { useCallback, useEffect, useState } from "react";

export function useAsync<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => load().then(setData, (e: Error) => setError(e.message)), deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, setError, reload };
}

export async function run(action: () => Promise<unknown>, after: () => unknown, onError: (m: string) => void) {
  try {
    await action();
    onError("");
    await after();
  } catch (e) {
    onError((e as Error).message);
  }
}
