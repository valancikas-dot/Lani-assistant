import React, { useEffect, useState } from "react";
import { getPolicyRules, evaluatePolicy } from "../lib/api";
import type { PolicyDecision, PolicyRule } from "../lib/types";

const VERDICT_STYLE: Record<string, { bg: string; color: string; label: string }> = {
  allow: { bg: "#14532d", color: "#4ade80", label: "✅ Allow" },
  require_approval: { bg: "#1e3a5f", color: "#60a5fa", label: "🔐 Require Approval" },
  deny: { bg: "#4c0519", color: "#f87171", label: "🚫 Deny" },
};

const VerdictBadge: React.FC<{ verdict: string }> = ({ verdict }) => {
  const style = VERDICT_STYLE[verdict] ?? { bg: "#333", color: "#fff", label: verdict };
  return (
    <span
      style={{
        background: style.bg,
        color: style.color,
        borderRadius: 6,
        padding: "4px 12px",
        fontWeight: 700,
        fontSize: 13,
      }}
    >
      {style.label}
    </span>
  );
};

export const PoliciesPage: React.FC = () => {
  const [rules, setRules] = useState<PolicyRule[]>([]);
  const [loadingRules, setLoadingRules] = useState(true);

  // Evaluation form
  const [action, setAction] = useState("");
  const [paramsText, setParamsText] = useState("{}");
  const [evaluating, setEvaluating] = useState(false);
  const [decision, setDecision] = useState<PolicyDecision | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);

  useEffect(() => {
    getPolicyRules()
      .then((res) => setRules(res.rules))
      .catch(() => setRules([]))
      .finally(() => setLoadingRules(false));
  }, []);

  const handleEvaluate = async () => {
    setEvalError(null);
    setDecision(null);
    let params: Record<string, unknown> = {};
    try {
      params = JSON.parse(paramsText);
    } catch {
      setEvalError("Invalid JSON in params");
      return;
    }
    if (!action.trim()) { setEvalError("Action name is required"); return; }
    setEvaluating(true);
    try {
      const res = await evaluatePolicy(action.trim(), params);
      setDecision(res);
    } catch (e: any) {
      setEvalError(e?.message ?? "Evaluation failed");
    } finally {
      setEvaluating(false);
    }
  };

  return (
    <div className="page policies-page" style={{ padding: "1.5rem" }}>
      <h1 style={{ margin: "0 0 0.25rem", fontSize: "1.4rem" }}>🛡️ Policy Engine</h1>
      <p style={{ margin: "0 0 1.5rem", color: "var(--color-text-muted, #888)", fontSize: 13 }}>
        Pre-execution policy rules that determine whether an action is allowed, requires approval, or is denied.
      </p>

      {/* Rules list */}
      <h2 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>Active Rules</h2>
      {loadingRules ? (
        <p>Loading rules…</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginBottom: "2rem" }}>
          {rules.map((rule, i) => (
            <div
              key={`${rule.priority}-${i}`}
              style={{
                background: "var(--color-bg-surface, #1a1a1a)",
                border: "1px solid var(--color-border, #333)",
                borderRadius: 8,
                padding: "0.75rem 1rem",
                display: "flex",
                alignItems: "flex-start",
                gap: "0.75rem",
              }}
            >
              <span style={{ color: "var(--color-text-muted, #666)", fontSize: 12, minWidth: 22, paddingTop: 2 }}>
                #{i + 1}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.25rem" }}>
                  <strong style={{ fontSize: 13, fontFamily: "monospace" }}>{rule.condition}</strong>
                  <VerdictBadge verdict={rule.verdict} />
                  <span style={{ fontSize: 11, color: "var(--color-text-muted, #888)", marginLeft: "auto" }}>
                    priority {rule.priority}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: 13, color: "var(--color-text-muted, #aaa)" }}>
                  {rule.description}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Test form */}
      <h2 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>Test an Action</h2>
      <div
        style={{
          background: "var(--color-bg-surface, #1a1a1a)",
          border: "1px solid var(--color-border, #333)",
          borderRadius: 8,
          padding: "1rem",
          marginBottom: "1rem",
        }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "0.75rem" }}>
          <div>
            <label style={{ display: "block", fontSize: 12, color: "var(--color-text-muted, #aaa)", marginBottom: 4 }}>
              Action name
            </label>
            <input
              type="text"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              placeholder="e.g. send_email"
              style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid var(--color-border, #333)", background: "var(--color-bg, #111)", color: "inherit", boxSizing: "border-box" }}
            />
          </div>
          <div>
            <label style={{ display: "block", fontSize: 12, color: "var(--color-text-muted, #aaa)", marginBottom: 4 }}>
              Params (JSON)
            </label>
            <input
              type="text"
              value={paramsText}
              onChange={(e) => setParamsText(e.target.value)}
              placeholder='{"key": "value"}'
              style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid var(--color-border, #333)", background: "var(--color-bg, #111)", color: "inherit", fontFamily: "monospace", fontSize: 12, boxSizing: "border-box" }}
            />
          </div>
        </div>

        {evalError && <p style={{ color: "#ef4444", fontSize: 13, margin: "0 0 0.5rem" }}>{evalError}</p>}

        <button
          className="btn btn-primary"
          onClick={handleEvaluate}
          disabled={evaluating}
          style={{ fontSize: 13 }}
        >
          {evaluating ? "Evaluating…" : "Evaluate →"}
        </button>
      </div>

      {/* Decision result */}
      {decision && (
        <div
          style={{
            background: "var(--color-bg-surface, #1a1a1a)",
            border: "1px solid var(--color-border, #333)",
            borderRadius: 8,
            padding: "1rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem" }}>
            <VerdictBadge verdict={decision.verdict} />
            <span style={{ fontSize: 13, color: "var(--color-text-muted, #aaa)" }}>
              Risk level: <strong style={{ color: "#fff" }}>{decision.risk_level}</strong>
            </span>
            <span style={{ fontSize: 13, color: "var(--color-text-muted, #aaa)" }}>
              Action: <strong style={{ fontFamily: "monospace", color: "#fff" }}>{decision.action}</strong>
            </span>
          </div>
          <p style={{ margin: 0, fontSize: 14 }}>{decision.reason}</p>
        </div>
      )}
    </div>
  );
};

export default PoliciesPage;
