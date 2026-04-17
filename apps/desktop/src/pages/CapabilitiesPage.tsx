import React, { useEffect, useState, useCallback } from "react";
import { getCapabilities, refreshCapabilities } from "../lib/api";
import type { CapabilityMeta } from "../lib/types";

const RISK_COLORS: Record<string, string> = {
  low: "#22c55e",
  medium: "#f59e0b",
  high: "#ef4444",
  critical: "#7c3aed",
};

const RISK_LABELS: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const RiskBadge: React.FC<{ level: string }> = ({ level }) => (
  <span
    style={{
      background: RISK_COLORS[level] ?? "#6b7280",
      color: "#fff",
      borderRadius: 4,
      padding: "2px 8px",
      fontSize: 11,
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: 0.5,
    }}
  >
    {RISK_LABELS[level] ?? level}
  </span>
);

export const CapabilitiesPage: React.FC = () => {
  const [capabilities, setCapabilities] = useState<CapabilityMeta[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getCapabilities({
        category: categoryFilter || undefined,
        risk_level: riskFilter || undefined,
      });
      setCapabilities(res.capabilities);
      setTotal(res.total);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load capabilities");
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, riskFilter]);

  useEffect(() => { void load(); }, [load]);

  const handleRefresh = async () => {
    try {
      await refreshCapabilities();
      await load();
    } catch {
      /* noop */
    }
  };

  const categories = Array.from(new Set(capabilities.map((c) => c.category))).sort();
  const filtered = capabilities.filter(
    (c) =>
      !search ||
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.description.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="page capabilities-page" style={{ padding: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.4rem" }}>🔧 Capabilities</h1>
          <p style={{ margin: "0.25rem 0 0", color: "var(--color-text-muted, #888)", fontSize: 13 }}>
            {total} registered tools with risk and policy metadata
          </p>
        </div>
        <button className="btn" onClick={handleRefresh} style={{ fontSize: 13 }}>
          ↻ Refresh Registry
        </button>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap" }}>
        <input
          type="text"
          placeholder="Search capabilities…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid var(--color-border, #333)", background: "var(--color-bg-surface, #1a1a1a)", color: "inherit", minWidth: 200 }}
        />
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid var(--color-border, #333)", background: "var(--color-bg-surface, #1a1a1a)", color: "inherit" }}
        >
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value)}
          style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid var(--color-border, #333)", background: "var(--color-bg-surface, #1a1a1a)", color: "inherit" }}
        >
          <option value="">All risk levels</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </div>

      {loading && <p>Loading…</p>}
      {error && <p style={{ color: "#ef4444" }}>Error: {error}</p>}

      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        {filtered.map((cap) => (
          <div
            key={cap.name}
            style={{
              background: "var(--color-bg-surface, #1a1a1a)",
              border: "1px solid var(--color-border, #333)",
              borderRadius: 8,
              padding: "0.75rem 1rem",
              cursor: "pointer",
            }}
            onClick={() => setExpanded(expanded === cap.name ? null : cap.name)}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
              <span style={{ fontWeight: 600, fontSize: 14, fontFamily: "monospace" }}>{cap.name}</span>
              <RiskBadge level={cap.risk_level} />
              {cap.requires_approval && (
                <span style={{ background: "#1e3a5f", color: "#60a5fa", borderRadius: 4, padding: "2px 8px", fontSize: 11 }}>
                  ✋ Needs Approval
                </span>
              )}
              <span style={{ color: "var(--color-text-muted, #888)", fontSize: 12, marginLeft: "auto" }}>
                {cap.category}
              </span>
            </div>
            <p style={{ margin: "0.5rem 0 0", fontSize: 13, color: "var(--color-text-muted, #aaa)" }}>
              {cap.description}
            </p>

            {expanded === cap.name && (
              <div style={{ marginTop: "0.75rem", borderTop: "1px solid var(--color-border, #333)", paddingTop: "0.75rem", fontSize: 13 }}>
                {cap.side_effects.length > 0 && (
                  <div style={{ marginBottom: "0.5rem" }}>
                    <strong>Side Effects:</strong>{" "}
                    <span style={{ color: "#f59e0b" }}>{cap.side_effects.join(", ")}</span>
                  </div>
                )}
                {cap.allowed_accounts.length > 0 && (
                  <div style={{ marginBottom: "0.5rem" }}>
                    <strong>Required Accounts:</strong>{" "}
                    {cap.allowed_accounts.join(", ")}
                  </div>
                )}
                <div style={{ marginBottom: "0.5rem" }}>
                  <strong>Retry Policy:</strong>{" "}
                  max {cap.retry_policy.max_retries} retries, {cap.retry_policy.backoff_seconds}s backoff
                </div>
                {Object.keys(cap.input_schema?.properties ?? {}).length > 0 && (
                  <div>
                    <strong>Parameters:</strong>{" "}
                    {Object.keys(cap.input_schema.properties as Record<string, unknown>).join(", ")}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default CapabilitiesPage;
