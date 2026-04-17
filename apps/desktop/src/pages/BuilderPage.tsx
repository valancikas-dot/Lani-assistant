/**
 * BuilderPage – main UI for Builder Mode.
 *
 * Lets users describe a project goal, pick a template, and have Lani
 * scaffold the full project structure with proposed terminal commands.
 */

import React, { useState } from "react";
import { useBuilderStore } from "../stores/builderStore";
import { useI18n } from "../i18n/useI18n";
import type { ProjectTemplate, ProjectTreeNode } from "../lib/types";

// ─── Template options ─────────────────────────────────────────────────────────

const TEMPLATES: { value: ProjectTemplate; label: string; icon: string }[] = [
  { value: "react-ts",     label: "React + TypeScript",  icon: "⚛️" },
  { value: "nextjs",       label: "Next.js",              icon: "▲" },
  { value: "fastapi",      label: "FastAPI (Python)",     icon: "🐍" },
  { value: "node-express", label: "Node + Express",       icon: "🟩" },
  { value: "mobile-expo",  label: "React Native (Expo)",  icon: "📱" },
  { value: "static-html",  label: "Static HTML/CSS/JS",   icon: "🌐" },
  { value: "python-script",label: "Python Script",        icon: "🔧" },
  { value: "generic",      label: "Generic / Other",      icon: "📁" },
];

// ─── Sub-components ───────────────────────────────────────────────────────────

interface TreeNodeProps {
  node: ProjectTreeNode;
  depth?: number;
}

const TreeNode: React.FC<TreeNodeProps> = ({ node, depth = 0 }) => {
  const [open, setOpen] = useState(depth < 2);
  const indent = depth * 16;

  return (
    <div>
      <div
        className="builder__tree-node"
        style={{ paddingLeft: indent }}
        onClick={() => node.is_dir && setOpen((o) => !o)}
        role={node.is_dir ? "button" : undefined}
        tabIndex={node.is_dir ? 0 : undefined}
      >
        <span className="builder__tree-icon">
          {node.is_dir ? (open ? "📂" : "📁") : "📄"}
        </span>
        <span className="builder__tree-name">{node.name}</span>
      </div>
      {node.is_dir && open && node.children?.map((child) => (
        <TreeNode key={child.path} node={child} depth={depth + 1} />
      ))}
    </div>
  );
};

interface CommandBadgeProps {
  risk: string;
}
const CommandBadge: React.FC<CommandBadgeProps> = ({ risk }) => {
  const colors: Record<string, string> = {
    safe: "builder__badge--safe",
    moderate: "builder__badge--moderate",
    destructive: "builder__badge--destructive",
  };
  return <span className={`builder__badge ${colors[risk] ?? ""}`}>{risk}</span>;
};

// ─── Main page ────────────────────────────────────────────────────────────────

export const BuilderPage: React.FC = () => {
  const { t } = useI18n();

  const {
    goal, template, projectName, baseDir, features,
    taskResult, treeRoot, commands,
    loading, treeLoading, error, success,
    setGoal, setTemplate, setProjectName, setBaseDir,
    addFeature, removeFeature,
    submitTask, reset,
  } = useBuilderStore();

  const [featureInput, setFeatureInput] = useState("");
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const handleAddFeature = () => {
    const val = featureInput.trim();
    if (val) {
      addFeature(val);
      setFeatureInput("");
    }
  };

  const handleCopy = (text: string, idx: number) => {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 1500);
  };

  return (
    <div className="builder page-container">
      {/* ── Header ── */}
      <div className="page-header">
        <h1 className="page-title">🏗️ {t("builder", "title")}</h1>
        <p className="page-subtitle">{t("builder", "subtitle")}</p>
      </div>

      <div className="builder__layout">
        {/* ── Left panel: inputs ── */}
        <section className="builder__panel builder__panel--input">
          <h2 className="builder__section-title">{t("builder", "describe_project")}</h2>

          {/* Goal */}
          <label className="builder__label" htmlFor="builder-goal">
            {t("builder", "goal_label")}
          </label>
          <textarea
            id="builder-goal"
            className="builder__textarea"
            rows={3}
            placeholder={t("builder", "goal_placeholder")}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            disabled={loading}
          />

          {/* Template */}
          <label className="builder__label">{t("builder", "template_label")}</label>
          <div className="builder__templates">
            {TEMPLATES.map((tpl) => (
              <button
                key={tpl.value}
                className={`builder__template-btn${template === tpl.value ? " builder__template-btn--active" : ""}`}
                onClick={() => setTemplate(tpl.value)}
                disabled={loading}
              >
                <span>{tpl.icon}</span>
                <span>{tpl.label}</span>
              </button>
            ))}
          </div>

          {/* Optional: project name & base dir */}
          <details className="builder__advanced">
            <summary className="builder__advanced-summary">{t("builder", "advanced")}</summary>
            <label className="builder__label" htmlFor="builder-name">
              {t("builder", "project_name_label")}
            </label>
            <input
              id="builder-name"
              className="builder__input"
              type="text"
              placeholder={t("builder", "project_name_placeholder")}
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              disabled={loading}
            />
            <label className="builder__label" htmlFor="builder-dir">
              {t("builder", "base_dir_label")}
            </label>
            <input
              id="builder-dir"
              className="builder__input"
              type="text"
              placeholder={t("builder", "base_dir_placeholder")}
              value={baseDir}
              onChange={(e) => setBaseDir(e.target.value)}
              disabled={loading}
            />
          </details>

          {/* Features */}
          <label className="builder__label">{t("builder", "features_label")}</label>
          <div className="builder__feature-input">
            <input
              className="builder__input"
              type="text"
              placeholder={t("builder", "features_placeholder")}
              value={featureInput}
              onChange={(e) => setFeatureInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddFeature()}
              disabled={loading}
            />
            <button
              className="btn btn--secondary"
              onClick={handleAddFeature}
              disabled={loading || !featureInput.trim()}
            >
              +
            </button>
          </div>
          {features.length > 0 && (
            <div className="builder__feature-tags">
              {features.map((f) => (
                <span key={f} className="builder__feature-tag">
                  {f}
                  <button
                    className="builder__feature-tag-remove"
                    onClick={() => removeFeature(f)}
                    aria-label={`Remove ${f}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* Actions */}
          <div className="builder__actions">
            <button
              className="btn btn--primary"
              onClick={() => void submitTask()}
              disabled={loading || !goal.trim()}
            >
              {loading ? t("builder", "building") : t("builder", "build_btn")}
            </button>
            {taskResult && (
              <button className="btn btn--ghost" onClick={reset} disabled={loading}>
                {t("builder", "reset_btn")}
              </button>
            )}
          </div>

          {/* Status messages */}
          {error && <p className="builder__error">{error}</p>}
          {success && !error && <p className="builder__success">{success}</p>}
        </section>

        {/* ── Right panel: results ── */}
        {taskResult && (
          <section className="builder__panel builder__panel--results">

            {/* Steps taken */}
            <h2 className="builder__section-title">{t("builder", "steps_title")}</h2>
            <ol className="builder__steps">
              {taskResult.steps_taken.map((step, i) => (
                <li key={i} className="builder__step">✅ {step}</li>
              ))}
            </ol>

            {/* Files created */}
            {taskResult.files_created.length > 0 && (
              <>
                <h2 className="builder__section-title">{t("builder", "files_title")}</h2>
                <ul className="builder__file-list">
                  {taskResult.files_created.map((f) => (
                    <li key={f} className="builder__file-item">
                      <span className="builder__file-icon">📄</span>
                      <span className="builder__file-path">{f}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {/* File tree */}
            {(treeLoading || treeRoot) && (
              <>
                <h2 className="builder__section-title">{t("builder", "tree_title")}</h2>
                {treeLoading ? (
                  <p className="builder__loading">{t("builder", "tree_loading")}</p>
                ) : treeRoot ? (
                  <div className="builder__tree">
                    <TreeNode node={treeRoot} />
                  </div>
                ) : null}
              </>
            )}

            {/* Proposed commands */}
            {commands.length > 0 && (
              <>
                <h2 className="builder__section-title">{t("builder", "commands_title")}</h2>
                <p className="builder__commands-note">{t("builder", "commands_note")}</p>
                <div className="builder__commands">
                  {commands.map((cmd, i) => (
                    <div key={i} className="builder__command-card">
                      <div className="builder__command-header">
                        <code className="builder__command-code">{cmd.command}</code>
                        <div className="builder__command-meta">
                          <CommandBadge risk={cmd.risk} />
                          {cmd.requires_approval && (
                            <span className="builder__badge builder__badge--approval">
                              {t("builder", "approval_required")}
                            </span>
                          )}
                          <button
                            className="builder__copy-btn"
                            onClick={() => handleCopy(cmd.command, i)}
                            title="Copy command"
                          >
                            {copiedIdx === i ? "✅" : "📋"}
                          </button>
                        </div>
                      </div>
                      <p className="builder__command-desc">{cmd.description}</p>
                      {cmd.cwd && (
                        <p className="builder__command-cwd">📂 {cmd.cwd}</p>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>
        )}
      </div>
    </div>
  );
};

export default BuilderPage;
