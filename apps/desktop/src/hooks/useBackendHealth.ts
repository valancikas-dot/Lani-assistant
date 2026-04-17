/**
 * useBackendHealth – polls the health endpoint and reports connectivity.
 */

import { useState, useEffect } from "react";
import { checkHealth } from "../lib/api";

export function useBackendHealth(intervalMs = 10_000) {
  const [isOnline, setIsOnline] = useState<boolean | null>(null);

  useEffect(() => {
    const poll = async () => {
      try {
        await checkHealth();
        setIsOnline(true);
      } catch {
        setIsOnline(false);
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return { isOnline };
}
