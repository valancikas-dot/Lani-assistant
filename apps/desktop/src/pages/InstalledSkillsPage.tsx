/**
 * InstalledSkillsPage – Phase 9: Installed Skills Registry + Versioning
 *
 * Displays all installed generated skills with:
 *   • Status badge + risk badge + version tag
 *   • Source lineage (Draft #N from Proposal #M)
 *   • Enable / Disable / Rollback / Revoke action buttons
 *   • Expandable version history table
 *
 * Safety
 * ──────
 * • Revoke is permanent — a confirmation prompt is shown first.
 * • Rollback is explicit and audited.
 * • No code is executed by this page.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  listInstalledSkills,
  getInstalledSkillVersions,
  enableInstalledSkill,
  disableInstalledSkill,
  rollbackInstalledSkill,
  revokeInstalledSkill,
} from "../lib/api";
import type {
  InstalledSkill,
  InstalledSkillStatus,
  InstalledSkillVersion,
} from "../lib/types";

// ─── Badges ───────────────────────────────────────────────────────────────────

const RISK_CLASSES: Record<string, string> = {
  low:      "risk-badge risk-badge--low",
  medium:   "risk-badge risk-badge--medium",
  high:     "risk-badge risk-badge--high",
  critical: "risk-badge risk-badge--critical",
};

const RiskBadge: React.FC<{ level: string }> = ({ level }) => (
  <span className={RISK_CLASSES[level] ?? "risk-badge risk-badge--unknown"}>
    {level}
  </span>
);

const STATUS_CLASSES: Record<InstalledSkillStatus, string> = {
  installed:  "status-badge status-badge--success",
  disabled:   "status-badge status-badge--warning",
  superseded: "status-badge status-badge--info",
  revoked:    "status-badge status-badge--rejected",
};

const STATUS_LABELS: Record<InstalledSkillStatus, string> = {
  installed:  "Installed",
  disabled:   "Disabled",
  superseded: "Superseded",
  revoked:    "Revoked",
};

const SkillStatusBadge: React.FC<{ status: InstalledSkillStatus }> = ({ status }) => (
  <span className={STATUS_CLASSES[status] ?? "status-badge"}>
    {STATUS_LABELS[status] ?? status}
  </span>
);

// ─── Version history table ────────────────────────────────────────────────────

const VersionHistory: React.FC<{ skillId: number }> = ({ skillId }) => {
  const [versions, setVersions] = useState<InstalledSkillVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = async () => {
    if (loaded) return;
    setLoading(true);
    try {
      const res = await getInstalledSkillVersions(skillId);
      setVersions(res.versions);
      setLoaded(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <details className="skill-reg__history" onToggle={(e) => {
      if ((e.target as HTMLDetailsElement).open) void load();
    }}>
      <summary className="skill-reg__history-toggle">📜 Version history</summary>
      {loading && <p className="skill-reg__history-loading">Loading…</p>}
      {loaded && versions.length === 0 && (
        <p className="skill-reg__history-empty">No version records yet.</p>
      )}
      {loaded && versions.length > 0 && (
        <table className="skill-reg__history-table">
          <thead>
            <tr>
              <th>Version</th>
              <th>Action</th>
              <th>Draft</th>
              <th>Risk</th>
              <th>Note</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id}>
                <td><code>{v.version}</code></td>
                <td>{v.action}</td>
                <td>#{v.source_draft_id}</td>
                <td><RiskBadge level={v.risk_level} /></td>
                <td className="skill-reg__history-note">{v.note ?? "—"}</td>
                <td className="skill-reg__history-date">
                  {v.created_at ? new Date(v.created_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
};

// ─── Skill Card ───────────────────────────────────────────────────────────────

const SkillCard: React.FC<{
  skill: InstalledSkill;
  onEnable: (id: number) => void;
  onDisable: (id: number) => void;
  onRollback: (id: number) => void;
  onRevoke: (id: number, reason: string) => void;
  isBusy: boolean;
}> = ({ skill, onEnable, onDisable, onRollback, onRevoke, isBusy }) => {
  const isTerminal = skill.status === "revoked" || skill.status === "superseded";

  const handleRevoke = () => {
    const reason = window.prompt(
      `Permanently revoke "${skill.name}"?\n\nThis cannot be undone.\n\nEnter a reason (or leave blank):`,
    );
    if (reason === null) return; // user cancelled
    onRevoke(skill.id, reason);
  };

  return (
    <div
      className={[
        "skill-card",
        `skill-card--${skill.status}`,
        isTerminal ? "skill-card--dismissed" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {/* Header */}
      <div className="skill-card__header">
        <div className="skill-card__title-row">
          <span className="skill-card__title">{skill.name}</span>
          <SkillStatusBadge status={skill.status} />
          <RiskBadge level={skill.risk_level} />
          <span className="skill-card__version">v{skill.current_version}</span>
        </div>
        <div className="skill-card__meta">
          <span className="skill-card__meta-item">
            📋 Draft #{skill.source_draft_id}
            {skill.source_proposal_id != null &&
              ` · Proposal #${skill.source_proposal_id}`}
          </span>
          {skill.installed_at && (
            <span className="skill-card__meta-item skill-card__meta-item--muted">
              Installed {new Date(skill.installed_at).toLocaleString()}
            </span>
          )}
          {skill.last_used_at && (
            <span className="skill-card__meta-item skill-card__meta-item--muted">
              Last used {new Date(skill.last_used_at).toLocaleString()}
            </span>
          )}
          {skill.use_count > 0 && (
            <span className="skill-card__meta-item skill-card__meta-item--muted">
              Used {skill.use_count}×
            </span>
          )}
          {skill.rollback_version && (
            <span className="skill-card__meta-item skill-card__meta-item--muted">
              Rollback → v{skill.rollback_version}
            </span>
          )}
        </div>
      </div>

      {/* Description */}
      {skill.description && (
        <p className="skill-card__description">{skill.description}</p>
      )}

      {/* Revoke reason */}
      {skill.revoke_reason && (
        <div className="skill-card__install-note skill-card__install-note--error">
          🚫 Revoked: {skill.revoke_reason}
        </div>
      )}

      {/* Version history */}
      <VersionHistory skillId={skill.id} />

      {/* Actions */}
      {!isTerminal && (
        <div className="skill-card__actions">
          {skill.status === "disabled" && (
            <button
              className="btn btn--primary btn--sm"
              disabled={isBusy}
              onClick={() => onEnable(skill.id)}
              title="Re-activate this skill"
            >
              ▶ Enable
            </button>
          )}
          {skill.status === "installed" && (
            <button
              className="btn btn--secondary btn--sm"
              disabled={isBusy}
              onClick={() => onDisable(skill.id)}
              title="Temporarily disable — can be re-enabled"
            >
              ⏸ Disable
            </button>
          )}
          {skill.rollback_version && (
            <button
              className="btn btn--ghost btn--sm"
              disabled={isBusy}
              onClick={() => onRollback(skill.id)}
              title={`Roll back to v${skill.rollback_version}`}
            >
              ↩ Rollback to v{skill.rollback_version}
            </button>
          )}
          <button
            className="btn btn--ghost btn--xs skill-card__dismiss-btn"
            disabled={isBusy}
            onClick={handleRevoke}
            title="Permanently revoke — cannot be undone"
          >
            🚫 Revoke
          </button>
        </div>
      )}
    </div>
  );
};

// ─── Filter tabs ──────────────────────────────────────────────────────────────

const FILTER_OPTIONS = [
  { label: "All",        value: undefined        as string | undefined },
  { label: "Installed",  value: "installed"                            },
  { label: "Disabled",   value: "disabled"                             },
  { label: "Superseded", value: "superseded"                           },
  { label: "Revoked",    value: "revoked"                              },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export const InstalledSkillsPage: React.FC = () => {
  const [skills, setSkills] = useState<InstalledSkill[]>([]);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [isLoading, setIsLoading] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listInstalledSkills(statusFilter);
      setSkills(res.skills);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load skills");
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (
    id: number,
    fn: () => Promise<{ ok: boolean; skill: InstalledSkill }>,
    successMsg: (s: InstalledSkill) => string,
  ) => {
    setBusyId(id);
    setMessage(null);
    setError(null);
    try {
      const res = await fn();
      setSkills((prev) => prev.map((s) => (s.id === id ? res.skill : s)));
      setMessage(successMsg(res.skill));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleEnable = (id: number) =>
    act(
      id,
      () => enableInstalledSkill(id),
      (s) => `✅ "${s.name}" enabled.`,
    );

  const handleDisable = (id: number) =>
    act(
      id,
      () => disableInstalledSkill(id),
      (s) => `⏸ "${s.name}" disabled.`,
    );

  const handleRollback = (id: number) =>
    act(
      id,
      () => rollbackInstalledSkill(id),
      (s) => `↩ "${s.name}" rolled back to v${s.current_version}.`,
    );

  const handleRevoke = (id: number, reason: string) =>
    act(
      id,
      () => revokeInstalledSkill(id, reason),
      (s) => `🚫 "${s.name}" permanently revoked.`,
    );

  const activeCount = skills.filter(
    (s) => s.status === "installed" || s.status === "disabled",
  ).length;

  return (
    <div className="page installed-skills-page">
      {/* Header */}
      <div className="page__header">
        <h1>
          Installed Skills
          {activeCount > 0 && (
            <span className="page__badge">{activeCount}</span>
          )}
        </h1>
        <p className="page__subtitle">
          Registry of fully-installed generated skills. Enable, disable,
          roll back, or permanently revoke individual skills. Disabled and
          revoked skills cannot execute.
        </p>
      </div>

      {/* Toolbar */}
      <div className="skill-proposals-page__toolbar">
        <div className="skill-proposals-page__actions">
          <button
            className="btn btn--secondary btn--sm"
            onClick={() => void load()}
            disabled={isLoading}
          >
            ↺ Refresh
          </button>
          <a href="/skill-drafts" className="btn btn--ghost btn--sm">
            ← Skill Drafts
          </a>
        </div>

        {/* Filter tabs */}
        <div className="skill-proposals-page__filters" role="tablist">
          {FILTER_OPTIONS.map((opt) => (
            <button
              key={opt.label}
              role="tab"
              aria-selected={statusFilter === opt.value}
              className={[
                "skill-proposals-page__filter-btn",
                statusFilter === opt.value
                  ? "skill-proposals-page__filter-btn--active"
                  : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => setStatusFilter(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Messages */}
      {message && (
        <div className="skill-proposals-page__message skill-proposals-page__message--ok">
          {message}
        </div>
      )}
      {error && (
        <div className="skill-proposals-page__message skill-proposals-page__message--error">
          {error}
        </div>
      )}

      {/* Content */}
      {isLoading && skills.length === 0 ? (
        <p className="page__loading">Loading installed skills…</p>
      ) : skills.length === 0 ? (
        <div className="page__empty">
          <p>No installed skills{statusFilter ? ` with status "${statusFilter}"` : ""}.</p>
          <p className="page__empty-hint">
            Go to{" "}
            <a href="/skill-drafts" className="skill-card__chain-link">
              Skill Drafts
            </a>
            , approve a draft, request installation, get it approved in{" "}
            <a href="/approvals" className="skill-card__chain-link">
              Approvals
            </a>
            , then click <strong>"Finalize Install"</strong>.
          </p>
        </div>
      ) : (
        <div className="skill-proposals-page__list">
          {skills.map((s) => (
            <SkillCard
              key={s.id}
              skill={s}
              onEnable={handleEnable}
              onDisable={handleDisable}
              onRollback={handleRollback}
              onRevoke={handleRevoke}
              isBusy={busyId === s.id}
            />
          ))}
        </div>
      )}
    </div>
  );
};
