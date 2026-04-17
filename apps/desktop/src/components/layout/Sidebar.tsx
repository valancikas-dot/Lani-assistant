/**
 * Sidebar – holographic navigation rail.
 */

import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useBackendHealth } from "../../hooks/useBackendHealth";
import { useApprovalsStore } from "../../stores/approvalsStore";
import { useI18n } from "../../i18n/useI18n";
import { useAuthStore } from "../../stores/authStore";

// SVG icon set – minimal, high-tech glyphs
const ICON: Record<string, React.ReactNode> = {
  home:        <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M10 2L2 8v10h5v-6h6v6h5V8L10 2z"/></svg>,
  chat:        <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M2 4a2 2 0 012-2h12a2 2 0 012 2v8a2 2 0 01-2 2H6l-4 3V4z"/></svg>,
  approvals:   <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M10 2a8 8 0 100 16A8 8 0 0010 2zm1 11H9V9h2v4zm0-6H9V5h2v2z"/></svg>,
  builder:     <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M3 4h14v2H3V4zm0 5h14v2H3V9zm0 5h8v2H3v-2z"/></svg>,
  connectors:  <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><circle cx="5" cy="10" r="3"/><circle cx="15" cy="10" r="3"/><path d="M8 10h4"/></svg>,
  operator:    <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><rect x="2" y="3" width="16" height="12" rx="2"/><path d="M7 17h6"/><path d="M10 15v2"/></svg>,
  security:    <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M10 2L3 5v5c0 4.4 3 8.4 7 9.3 4-.9 7-4.9 7-9.3V5l-7-3z"/></svg>,
  diagnostics: <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><polyline points="2,12 6,8 9,11 13,5 18,10"/></svg>,
  memory:      <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M10 2C6.13 2 3 5.13 3 9c0 2.39 1.19 4.5 3 5.74V17h8v-2.26C15.81 13.5 17 11.39 17 9c0-3.87-3.13-7-7-7zm-1 11H7v-2h2v2zm0-4H7V5h2v4zm4 4h-2v-2h2v2zm0-4h-2V5h2v4z"/></svg>,
  logs:        <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M4 3h12a1 1 0 011 1v12a1 1 0 01-1 1H4a1 1 0 01-1-1V4a1 1 0 011-1zm2 4v2h8V7H6zm0 4v2h5v-2H6z"/></svg>,
  settings:    <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M10 13a3 3 0 100-6 3 3 0 000 6zm7-3c0-.34-.03-.67-.08-1l2.16-1.68-2-3.46-2.54.97A7.01 7.01 0 0013 3.18V1H7v2.18A7 7 0 005.46 4.83l-2.54-.97-2 3.46L3.08 9C3.03 9.33 3 9.66 3 10s.03.67.08 1L.92 12.68l2 3.46 2.54-.97A7.01 7.01 0 007 16.82V19h6v-2.18a7 7 0 001.54-1.65l2.54.97 2-3.46L17.08 11c.05-.33.08-.66.08-1z"/></svg>,
  capabilities: <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M3 5h14M3 10h9M3 15h6"/><circle cx="16" cy="10" r="3"/></svg>,
  policies:    <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M10 2L3 5v5c0 4.4 3 8.4 7 9.3 4-.9 7-4.9 7-9.3V5l-7-3zm-1 9.5l-2.5-2.5 1.4-1.4 1.1 1.1 3.1-3.1 1.4 1.4L9 11.5z"/></svg>,
  state:       <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><rect x="2" y="2" width="7" height="7" rx="1"/><rect x="11" y="2" width="7" height="7" rx="1"/><rect x="2" y="11" width="7" height="7" rx="1"/><rect x="11" y="11" width="7" height="7" rx="1"/></svg>,
  evals:       <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M3 17V7l7-5 7 5v10H3zm5-1h4v-4H8v4z"/></svg>,
  mission:     <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><circle cx="10" cy="10" r="7"/><circle cx="10" cy="10" r="3" fill="none" stroke="currentColor" strokeWidth="2"/></svg>,
  skills:      <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M10 2l2.4 4.9 5.4.8-3.9 3.8.9 5.4L10 14.4 5.2 16.9l.9-5.4L2.2 7.7l5.4-.8L10 2z"/></svg>,
  profiles:    <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><circle cx="10" cy="7" r="3"/><path d="M3 18c0-3.87 3.13-7 7-7s7 3.13 7 7"/></svg>,
  modes:       <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><rect x="2" y="3" width="16" height="3" rx="1"/><rect x="2" y="9" width="11" height="3" rx="1"/><rect x="2" y="15" width="7" height="3" rx="1"/></svg>,
  tokens:      <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="2"/><text x="10" y="14" textAnchor="middle" fontSize="9" fill="currentColor">₮</text></svg>,
};

export const Sidebar: React.FC = () => {
  const { isOnline } = useBackendHealth();
  const approvals = useApprovalsStore((s) => s.approvals);
  const pendingCount = approvals.length;
  const { t } = useI18n();
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  const NAV_ITEMS = [
    { to: "/home",        label: t("nav", "home"),         iconKey: "home"        },
    { to: "/",            label: t("nav", "chat"),         iconKey: "chat"        },
    { to: "/approvals",   label: t("nav", "approvals"),   iconKey: "approvals"   },
    { to: "/builder",     label: t("nav", "builder"),     iconKey: "builder"     },
    { to: "/connectors",  label: t("nav", "connectors"),  iconKey: "connectors"  },
    { to: "/operator",    label: t("nav", "operator"),    iconKey: "operator"    },
    { to: "/security",    label: t("nav", "security"),    iconKey: "security"    },
    { to: "/diagnostics", label: t("nav", "diagnostics"), iconKey: "diagnostics" },
    { to: "/memory",       label: t("nav", "memory"),        iconKey: "memory"        },
    { to: "/logs",         label: t("nav", "logs"),          iconKey: "logs"          },
    { to: "/capabilities", label: t("nav", "capabilities"),  iconKey: "capabilities"  },
    { to: "/policies",     label: t("nav", "policies"),      iconKey: "policies"      },
    { to: "/state",        label: t("nav", "state"),         iconKey: "state"         },
    { to: "/evals",        label: t("nav", "evals"),         iconKey: "evals"         },
    { to: "/mission",      label: t("nav", "missions"),      iconKey: "mission"       },
    { to: "/skill-proposals", label: t("nav", "skill_proposals"), iconKey: "skills"   },
    { to: "/skill-drafts",    label: t("nav", "skill_drafts"),    iconKey: "skills"   },
    { to: "/missions",        label: t("nav", "autonomous_missions"), iconKey: "mission" },
    { to: "/installed-skills", label: t("nav", "installed_skills"), iconKey: "skills"  },
    { to: "/profiles",         label: t("nav", "profiles"),         iconKey: "profiles" },
    { to: "/modes",            label: t("nav", "modes"),            iconKey: "modes"    },
    { to: "/tokens",           label: "Tokenai",                    iconKey: "tokens"   },
    { to: "/settings",        label: t("nav", "settings"),        iconKey: "settings"  },
  ];

  const statusCls =
    isOnline === null  ? "sidebar__status--unknown"
    : isOnline         ? "sidebar__status--online"
    :                    "sidebar__status--offline";

  const statusText =
    isOnline === null  ? `◌ ${t("nav", "backend_connecting")}`
    : isOnline         ? `◉ ${t("nav", "backend_online")}`
    :                    `◎ ${t("nav", "backend_offline")}`;

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <div className="sidebar__logo">✦</div>
        <span className="sidebar__title">LANI</span>
      </div>

      <nav className="sidebar__nav">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `sidebar__nav-item${isActive ? " sidebar__nav-item--active" : ""}`
            }
          >
            <span className="sidebar__nav-icon">{ICON[item.iconKey]}</span>
            <span className="sidebar__nav-label">{item.label}</span>
            {item.to === "/approvals" && pendingCount > 0 && (
              <span className="sidebar__badge">{pendingCount}</span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar__footer">
        {/* Token balance */}
        {user && (
          <div style={{ marginBottom: "10px", padding: "8px 10px", background: "rgba(124,106,247,0.08)", borderRadius: "6px", border: "1px solid rgba(124,106,247,0.2)" }}>
            <div style={{ fontSize: "10px", color: "#9ca3af", letterSpacing: "0.08em", marginBottom: "2px" }}>
              {user.is_admin ? "👑 ADMIN" : "🪙 TOKENAI"}
            </div>
            <div style={{ fontSize: "13px", fontWeight: 600, color: user.is_admin ? "#fbbf24" : "#a78bfa" }}>
              {user.is_admin
                ? "∞ nemokama"
                : user.token_balance >= 1_000_000
                ? "999 999 999"
                : user.token_balance.toLocaleString("lt-LT")}
            </div>
            <div style={{ fontSize: "10px", color: "#6b7280", marginTop: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {user.email}
            </div>
            {!user.is_admin && (
              <button
                type="button"
                onClick={() => navigate("/tokens")}
                style={{ marginTop: "6px", fontSize: "10px", color: "#a78bfa", background: "none", border: "none", cursor: "pointer", padding: 0, letterSpacing: "0.05em", fontWeight: 600 }}
              >
                + Pirkti tokenus
              </button>
            )}
            <button
              type="button"
              onClick={logout}
              style={{ marginTop: "4px", fontSize: "10px", color: "#6b7280", background: "none", border: "none", cursor: "pointer", padding: 0, letterSpacing: "0.05em" }}
            >
              Atsijungti →
            </button>
          </div>
        )}
        <span className={`sidebar__status ${statusCls}`}>{statusText}</span>
      </div>
    </aside>
  );
};
