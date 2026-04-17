/**
 * LoginPage – login and register form.
 */

import React, { useState } from "react";
import { useAuthStore } from "../stores/authStore";

export const LoginPage: React.FC = () => {
  const { login, register, isLoading, error, clearError } = useAuthStore();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    if (mode === "register") {
      if (password !== confirm) return;
      await register(email, password);
    } else {
      await login(email, password);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg-primary, #0a0a0f)",
      }}
    >
      <div
        style={{
          width: "360px",
          padding: "40px",
          background: "var(--bg-secondary, #111118)",
          border: "1px solid var(--border, #2a2a3a)",
          borderRadius: "12px",
        }}
      >
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: "32px" }}>
          <div style={{ fontSize: "32px", marginBottom: "4px" }}>✦</div>
          <div style={{ fontSize: "22px", fontWeight: 700, letterSpacing: "0.15em", color: "var(--text-primary, #e8e8f0)" }}>
            LANI
          </div>
          <div style={{ fontSize: "11px", color: "var(--text-muted, #666)", letterSpacing: "0.2em", marginTop: "4px" }}>
            AI ASSISTANT
          </div>
        </div>

        {/* Tab switcher */}
        <div style={{ display: "flex", marginBottom: "24px", borderBottom: "1px solid var(--border, #2a2a3a)" }}>
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => { setMode(m); clearError(); }}
              style={{
                flex: 1,
                padding: "10px",
                background: "none",
                border: "none",
                borderBottom: mode === m ? "2px solid var(--accent, #7c6af7)" : "2px solid transparent",
                color: mode === m ? "var(--accent, #7c6af7)" : "var(--text-muted, #666)",
                fontWeight: mode === m ? 600 : 400,
                cursor: "pointer",
                fontSize: "13px",
                letterSpacing: "0.08em",
              }}
            >
              {m === "login" ? "PRISIJUNGTI" : "REGISTRUOTIS"}
            </button>
          ))}
        </div>

        <form onSubmit={(e) => void handleSubmit(e)}>
          <div style={{ marginBottom: "16px" }}>
            <label style={{ display: "block", fontSize: "11px", color: "var(--text-muted, #666)", marginBottom: "6px", letterSpacing: "0.08em" }}>
              EL. PAŠTAS
            </label>
            <input
              type="email"
              className="settings-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              style={{ width: "100%", boxSizing: "border-box" }}
              placeholder="vardas@gmail.com"
            />
          </div>

          <div style={{ marginBottom: mode === "register" ? "16px" : "24px" }}>
            <label style={{ display: "block", fontSize: "11px", color: "var(--text-muted, #666)", marginBottom: "6px", letterSpacing: "0.08em" }}>
              SLAPTAŽODIS
            </label>
            <input
              type="password"
              className="settings-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              style={{ width: "100%", boxSizing: "border-box" }}
              placeholder="••••••••"
            />
          </div>

          {mode === "register" && (
            <div style={{ marginBottom: "24px" }}>
              <label style={{ display: "block", fontSize: "11px", color: "var(--text-muted, #666)", marginBottom: "6px", letterSpacing: "0.08em" }}>
                PATVIRTINTI SLAPTAŽODĮ
              </label>
              <input
                type="password"
                className="settings-input"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                autoComplete="new-password"
                style={{ width: "100%", boxSizing: "border-box" }}
                placeholder="••••••••"
              />
              {confirm && password !== confirm && (
                <p style={{ fontSize: "11px", color: "#ef4444", marginTop: "4px" }}>
                  Slaptažodžiai nesutampa
                </p>
              )}
            </div>
          )}

          {error && (
            <div style={{ background: "rgba(239,68,68,0.1)", border: "1px solid #ef4444", borderRadius: "6px", padding: "10px", marginBottom: "16px", fontSize: "13px", color: "#ef4444" }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn btn--primary"
            style={{ width: "100%" }}
            disabled={isLoading || (mode === "register" && password !== confirm)}
          >
            {isLoading
              ? "..."
              : mode === "login"
              ? "Prisijungti"
              : "Sukurti paskyrą"}
          </button>

          {mode === "register" && (
            <p style={{ fontSize: "11px", color: "var(--text-muted, #666)", textAlign: "center", marginTop: "16px", lineHeight: 1.5 }}>
              Registruodamiesi gausite <strong style={{ color: "var(--accent, #7c6af7)" }}>5 000 nemokamų tokenų</strong> pradžiai.
            </p>
          )}
        </form>
      </div>
    </div>
  );
};
