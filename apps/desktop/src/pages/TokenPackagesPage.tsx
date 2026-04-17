/**
 * TokenPackagesPage – buy token packages via Stripe.
 */

import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  getTokenPackages,
  createCheckoutSession,
  fetchTokenBalance,
  fetchTokenHistory,
} from "../lib/api";
import type { TokenPackage, TokenBalance, TokenTransaction } from "../lib/api";
import { useAuthStore } from "../stores/authStore";

// ── Helper ─────────────────────────────────────────────────────────────────

function fmt(n: number) {
  return n >= 1_000_000_000
    ? "∞"
    : n.toLocaleString("lt-LT");
}

// ── Component ──────────────────────────────────────────────────────────────

export const TokenPackagesPage: React.FC = () => {
  const { user, fetchMe, token } = useAuthStore();
  const [packages, setPackages] = useState<TokenPackage[]>([]);
  const [balance, setBalance] = useState<TokenBalance | null>(null);
  const [history, setHistory] = useState<TokenTransaction[]>([]);
  const [loadingPkg, setLoadingPkg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const paymentStatus = searchParams.get("payment"); // "success" | "cancelled"

  useEffect(() => {
    void getTokenPackages().then(setPackages).catch(() => {});
    if (token) {
      void fetchTokenBalance().then(setBalance).catch(() => {});
      void fetchTokenHistory()
        .then((d) => setHistory(d.transactions))
        .catch(() => {});
      void fetchMe();
    }
  }, [token, fetchMe]);

  const handleBuy = async (pkg: TokenPackage) => {
    setError(null);
    setLoadingPkg(pkg.id);
    try {
      const data = await createCheckoutSession(pkg.id);
      // Open Stripe checkout in the system browser (works in Tauri too)
      window.open(data.checkout_url, "_blank");
    } catch (e: unknown) {
      setError((e as Error).message ?? "Nepavyko sukurti mokėjimo");
    } finally {
      setLoadingPkg(null);
    }
  };

  const isAdmin = user?.is_admin || user?.email === "valancikas@gmail.com";

  return (
    <div className="page" style={{ maxWidth: "860px", margin: "0 auto" }}>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="page__header">
        <h1>🪙 Tokenai</h1>
      </div>

      {/* ── Payment status banner ───────────────────────────────────────── */}
      {paymentStatus === "success" && (
        <div style={{ background: "rgba(34,197,94,0.1)", border: "1px solid #22c55e", borderRadius: "8px", padding: "14px 18px", marginBottom: "24px", color: "#22c55e" }}>
          ✅ Mokėjimas gautas! Tokenai bus pridėti per kelias sekundes.
        </div>
      )}
      {paymentStatus === "cancelled" && (
        <div style={{ background: "rgba(239,68,68,0.1)", border: "1px solid #ef4444", borderRadius: "8px", padding: "14px 18px", marginBottom: "24px", color: "#ef4444" }}>
          ❌ Mokėjimas atšauktas.
        </div>
      )}

      {/* ── Current balance ─────────────────────────────────────────────── */}
      <div style={{ background: "var(--bg-secondary, #111118)", border: "1px solid var(--border, #2a2a3a)", borderRadius: "10px", padding: "20px 24px", marginBottom: "32px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: "11px", color: "#6b7280", letterSpacing: "0.1em", marginBottom: "4px" }}>
            DABARTINIS BALANSAS
          </div>
          <div style={{ fontSize: "28px", fontWeight: 700, color: isAdmin ? "#fbbf24" : "#a78bfa" }}>
            {isAdmin
              ? "∞ nemokama"
              : balance
              ? fmt(balance.balance)
              : user
              ? fmt(user.token_balance)
              : "—"}{" "}
            {!isAdmin && <span style={{ fontSize: "14px", color: "#6b7280" }}>tokenų</span>}
          </div>
          {isAdmin && (
            <div style={{ fontSize: "12px", color: "#fbbf24", marginTop: "4px" }}>👑 Admin paskyra – viskas nemokama</div>
          )}
        </div>
        {balance && !isAdmin && (
          <div style={{ textAlign: "right", fontSize: "12px", color: "#6b7280" }}>
            <div>Iš viso nupirkta: <strong style={{ color: "#9ca3af" }}>{fmt(balance.lifetime_purchased)}</strong></div>
            <div>Iš viso panaudota: <strong style={{ color: "#9ca3af" }}>{fmt(balance.lifetime_used)}</strong></div>
          </div>
        )}
      </div>

      {/* ── Packages ────────────────────────────────────────────────────── */}
      {!isAdmin && (
        <>
          <h2 style={{ fontSize: "14px", letterSpacing: "0.1em", color: "#6b7280", marginBottom: "16px" }}>
            PIRKTI TOKENUS
          </h2>

          {error && (
            <div style={{ background: "rgba(239,68,68,0.1)", border: "1px solid #ef4444", borderRadius: "6px", padding: "12px 16px", marginBottom: "16px", color: "#ef4444", fontSize: "13px" }}>
              {error}
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "16px", marginBottom: "40px" }}>
            {packages.map((pkg) => (
              <div
                key={pkg.id}
                style={{
                  background: pkg.highlight ? "rgba(124,106,247,0.08)" : "var(--bg-secondary, #111118)",
                  border: pkg.highlight ? "1px solid rgba(124,106,247,0.5)" : "1px solid var(--border, #2a2a3a)",
                  borderRadius: "10px",
                  padding: "20px",
                  position: "relative",
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                {pkg.highlight && (
                  <div style={{ position: "absolute", top: "-10px", left: "50%", transform: "translateX(-50%)", background: "#7c6af7", color: "#fff", fontSize: "10px", fontWeight: 700, padding: "2px 10px", borderRadius: "10px", letterSpacing: "0.1em", whiteSpace: "nowrap" }}>
                    GERIAUSIAS VARIANTAS
                  </div>
                )}
                <div style={{ fontSize: "15px", fontWeight: 700, color: "var(--text-primary, #e8e8f0)", marginBottom: "6px" }}>
                  {pkg.name}
                </div>
                <div style={{ fontSize: "26px", fontWeight: 800, color: pkg.highlight ? "#a78bfa" : "var(--text-primary, #e8e8f0)", marginBottom: "4px" }}>
                  €{pkg.price_eur}
                </div>
                <div style={{ fontSize: "14px", color: "#a78bfa", fontWeight: 600, marginBottom: "4px" }}>
                  {fmt(pkg.tokens)} tokenų
                </div>
                <div style={{ fontSize: "11px", color: "#6b7280", marginBottom: "16px", flexGrow: 1 }}>
                  {pkg.description}
                </div>
                <div style={{ fontSize: "10px", color: "#4b5563", marginBottom: "12px" }}>
                  ~€{(pkg.price_eur / pkg.tokens * 1000).toFixed(2)} / 1 000 tok.
                </div>
                <button
                  className={`btn ${pkg.highlight ? "btn--primary" : "btn--secondary"}`}
                  style={{ width: "100%" }}
                  onClick={() => void handleBuy(pkg)}
                  disabled={loadingPkg === pkg.id}
                >
                  {loadingPkg === pkg.id ? "Kraunama…" : "Pirkti →"}
                </button>
              </div>
            ))}
          </div>

          <p style={{ fontSize: "11px", color: "#4b5563", textAlign: "center", marginBottom: "40px" }}>
            Mokėjimus apdoroja <strong>Stripe</strong>. Kortelės duomenys nesaugomi Lani serveriuose.
          </p>
        </>
      )}

      {/* ── Transaction history ──────────────────────────────────────────── */}
      {history.length > 0 && (
        <>
          <h2 style={{ fontSize: "14px", letterSpacing: "0.1em", color: "#6b7280", marginBottom: "16px" }}>
            OPERACIJŲ ISTORIJA
          </h2>
          <div style={{ border: "1px solid var(--border, #2a2a3a)", borderRadius: "8px", overflow: "hidden" }}>
            {history.map((tx, i) => (
              <div
                key={tx.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "10px 16px",
                  borderBottom: i < history.length - 1 ? "1px solid var(--border, #2a2a3a)" : "none",
                  background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)",
                }}
              >
                <div>
                  <div style={{ fontSize: "13px", color: "var(--text-primary, #e8e8f0)" }}>
                    {tx.description || tx.tx_type}
                  </div>
                  <div style={{ fontSize: "11px", color: "#6b7280" }}>
                    {new Date(tx.created_at).toLocaleString("lt-LT")}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: "14px", fontWeight: 600, color: tx.amount > 0 ? "#22c55e" : "#f87171" }}>
                    {tx.amount > 0 ? "+" : ""}{fmt(tx.amount)}
                  </div>
                  <div style={{ fontSize: "11px", color: "#6b7280" }}>
                    likutis: {fmt(tx.balance_after)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
};
