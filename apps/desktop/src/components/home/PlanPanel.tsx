/**
 * PlanPanel – shows pending approval requests on the Home screen.
 *
 * Connected to useApprovalsStore. Renders each approval with a brief
 * description, risk badge, and Approve / Deny buttons.
 */

import React, { useEffect } from "react";
import { useApprovalsStore } from "../../stores/approvalsStore";

// ─── Risk colour map ──────────────────────────────────────────────────────────

const RISK_COLOUR: Record<string, string> = {
  low:      "var(--green)",
  medium:   "var(--warning)",
  high:     "var(--magenta)",
  critical: "var(--magenta)",
};

// ─── Component ────────────────────────────────────────────────────────────────

export const PlanPanel: React.FC = () => {
  const { approvals, fetchApprovals, decide } = useApprovalsStore();

  useEffect(() => {
    void fetchApprovals();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (approvals.length === 0) return null;

  return (
    <div
      style={{
        background: "var(--bg-glass)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        border: "1px solid rgba(255,183,0,0.25)",
        borderRadius: "12px",
        padding: "1rem",
        boxShadow: "0 0 20px rgba(255,183,0,0.08)",
      }}
    >
      {/* Header */}
      <div style={{
        fontFamily: "var(--font-hud)",
        fontSize: "0.7rem",
        letterSpacing: "0.12em",
        textTransform: "uppercase" as const,
        color: "var(--warning)",
        marginBottom: "0.75rem",
        display: "flex",
        alignItems: "center",
        gap: "0.4rem",
      }}>
        <span>⚡</span>
        <span>Plan — Awaiting Approval</span>
        <span style={{
          marginLeft: "auto",
          background: "rgba(255,183,0,0.15)",
          border: "1px solid var(--warning)",
          borderRadius: "10px",
          padding: "0.1rem 0.5rem",
          fontSize: "0.65rem",
        }}>
          {approvals.length}
        </span>
      </div>

      {/* Approval rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
        {approvals.map((ap) => {
          const riskLevel = (ap as unknown as Record<string, unknown>)["risk_level"] as string | undefined;
          const riskColour = RISK_COLOUR[riskLevel ?? "low"] ?? "var(--text-muted)";
          return (
            <div
              key={ap.id}
              style={{
                background: "rgba(255,255,255,0.03)",
                border: "1px solid var(--border)",
                borderRadius: "8px",
                padding: "0.65rem 0.75rem",
              }}
            >
              {/* Tool + risk */}
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.25rem" }}>
                <span style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "0.75rem",
                  color: "var(--cyan)",
                }}>
                  {ap.tool_name}
                </span>
                <span style={{
                  fontSize: "0.65rem",
                  color: riskColour,
                  border: `1px solid ${riskColour}`,
                  borderRadius: "8px",
                  padding: "0.1rem 0.45rem",
                  opacity: 0.9,
                }}>
                  {riskLevel ?? "low"}
                </span>
              </div>

              {/* Command excerpt */}
              <p style={{
                fontSize: "0.78rem",
                color: "var(--text-muted)",
                marginBottom: "0.6rem",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap" as const,
              }}>
                {ap.command}
              </p>

              {/* Buttons */}
              <div style={{ display: "flex", gap: "0.4rem" }}>
                <button
                  onClick={() => void decide(ap.id, "approved")}
                  style={{
                    flex: 1,
                    padding: "0.35rem",
                    background: "rgba(0,255,136,0.1)",
                    border: "1px solid var(--green)",
                    borderRadius: "6px",
                    color: "var(--green)",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  ✓ Approve
                </button>
                <button
                  onClick={() => void decide(ap.id, "denied")}
                  style={{
                    flex: 1,
                    padding: "0.35rem",
                    background: "rgba(255,45,120,0.1)",
                    border: "1px solid var(--magenta)",
                    borderRadius: "6px",
                    color: "var(--magenta)",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  ✕ Deny
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
