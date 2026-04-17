/**
 * useAuditLogs – fetches audit log entries from the backend.
 */

import { useState, useEffect, useCallback } from "react";
import { getAuditLogs } from "../lib/api";
import type { AuditLog } from "../lib/types";

export function useAuditLogs(limit = 100) {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getAuditLogs(limit);
      setLogs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load logs");
    } finally {
      setIsLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    void fetch();
  }, [fetch]);

  return { logs, isLoading, error, refetch: fetch };
}
