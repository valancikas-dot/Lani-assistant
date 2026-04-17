/**
 * MemoryPage – review and manage the assistant's structured memory.
 *
 * Layout
 * ──────
 *   ┌──────────────────────────────────────────────────────────┐
 *   │  Memory                                       [+ Add]    │
 *   │  Suggestions (N)                                         │
 *   │  ┌─────────────────────────────────────────────────────┐ │
 *   │  │ 💡 "You saved presentations to ~/Slides 3 times…"   │ │
 *   │  │ [✔ Accept]  [✖ Dismiss]                             │ │
 *   │  └─────────────────────────────────────────────────────┘ │
 *   │                                                          │
 *   │  user_preferences (3)  workflow_preferences (2)  …       │
 *   │  ┌─────┬─────────────────────────┬──────────┬────────┐   │
 *   │  │ Pin │ Key / Value             │ Src/Conf │Actions │   │
 *   │  └─────┴─────────────────────────┴──────────┴────────┘   │
 *   └──────────────────────────────────────────────────────────┘
 */

import React, { useEffect, useState } from "react";
import { useMemoryStore } from "../stores/memoryStore";
import type { MemoryEntry, MemoryEntryCreate, MemoryCategory } from "../lib/types";
import { useI18n } from "../i18n/useI18n";

const ORDERED_CATEGORIES: MemoryCategory[] = [
  "user_preferences",
  "workflow_preferences",
  "task_history",
  "suggestions",
];

// ─── Suggestion card ──────────────────────────────────────────────────────────

const SuggestionCards: React.FC = () => {
  const { suggestions, acceptSuggestion, dismissSuggestion } = useMemoryStore();
  const { t } = useI18n();
  if (suggestions.length === 0) return null;

  return (
    <section className="memory-suggestions">
      <h2 className="memory-section-title">
        💡 {t("memory", "suggestions_title").replace(/^💡\s*/, "")}
        <span className="memory-count">{suggestions.length}</span>
      </h2>
      <div className="memory-suggestions__list">
        {suggestions.map((s) => (
          <div key={s.entry_id} className="suggestion-card">
            <p className="suggestion-card__text">{s.explanation}</p>
            <div className="suggestion-card__meta">
              <span className="memory-conf-bar">
                <span
                  className="memory-conf-fill"
                  style={{ width: `${Math.round(s.confidence * 100)}%` }}
                />
              </span>
              <span className="memory-conf-label">
                {Math.round(s.confidence * 100)}% {t("memory", "confidence")}
              </span>
            </div>
            <div className="suggestion-card__actions">
              <button
                className="mem-btn mem-btn--accept"
                onClick={() => acceptSuggestion(s.entry_id)}
              >
                {t("memory", "accept")}
              </button>
              <button
                className="mem-btn mem-btn--dismiss"
                onClick={() => dismissSuggestion(s.entry_id)}
              >
                {t("memory", "dismiss")}
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

// ─── Add entry form ────────────────────────────────────────────────────────────

interface AddFormProps {
  onClose: () => void;
}

const AddEntryForm: React.FC<AddFormProps> = ({ onClose }) => {
  const { createEntry } = useMemoryStore();
  const { t } = useI18n();
  const [category, setCategory] = useState<MemoryCategory>("user_preferences");
  const [key, setKey] = useState("");
  const [valueRaw, setValueRaw] = useState("{}");
  const [parseError, setParseError] = useState("");

  const categoryLabels: Record<string, string> = {
    user_preferences:    t("memory", "category_user_preferences"),
    workflow_preferences: t("memory", "category_workflow_preferences"),
    task_history:        t("memory", "category_task_history"),
    suggestions:         t("memory", "category_suggestions"),
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    let value: Record<string, unknown>;
    try {
      value = JSON.parse(valueRaw);
    } catch {
      setParseError("Value must be valid JSON.");
      return;
    }
    if (!key.trim()) return;

    const payload: MemoryEntryCreate = {
      category,
      key: key.trim(),
      value,
      source: "user_explicit",
      confidence: 1.0,
    };
    await createEntry(payload);
    onClose();
  };

  return (
    <div className="memory-add-form">
      <h3 className="memory-add-form__title">{t("memory", "add_form_title")}</h3>
      <form onSubmit={handleSubmit} className="memory-form">
        <label className="memory-form__label">
          {t("memory", "category_label")}
          <select
            className="memory-form__input"
            value={category}
            onChange={(e) => setCategory(e.target.value as MemoryCategory)}
          >
            {ORDERED_CATEGORIES.filter((c) => c !== "task_history" && c !== "suggestions").map(
              (c) => (
                <option key={c} value={c}>
                  {categoryLabels[c]}
                </option>
              )
            )}
          </select>
        </label>

        <label className="memory-form__label">
          {t("memory", "key_label")}
          <input
            className="memory-form__input"
            type="text"
            placeholder="e.g. preferred_output_folder"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            required
          />
        </label>

        <label className="memory-form__label">
          {t("memory", "value_label")} (JSON)
          <textarea
            className="memory-form__input memory-form__textarea"
            value={valueRaw}
            onChange={(e) => { setValueRaw(e.target.value); setParseError(""); }}
            rows={3}
            placeholder='{ "path": "/Users/you/Documents" }'
          />
          {parseError && <span className="memory-form__error">{parseError}</span>}
        </label>

        <div className="memory-form__actions">
          <button type="submit" className="mem-btn mem-btn--primary">Save</button>
          <button type="button" className="mem-btn mem-btn--ghost" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
};

// ─── Single entry row ──────────────────────────────────────────────────────────

interface EntryRowProps {
  entry: MemoryEntry;
}

const EntryRow: React.FC<EntryRowProps> = ({ entry }) => {
  const { deleteEntry, pinEntry, updateEntry } = useMemoryStore();
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [editRaw, setEditRaw] = useState(JSON.stringify(entry.value, null, 2));
  const [editError, setEditError] = useState("");

  const sourceLabels: Record<string, string> = {
    user_explicit:                  t("memory", "source_user_explicit"),
    inferred_from_repeated_actions: t("memory", "source_inferred"),
    settings_sync:                  t("memory", "source_settings_sync"),
    executor_outcome:               t("memory", "source_executor_outcome"),
  };

  const handleSave = async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(editRaw);
    } catch {
      setEditError("Invalid JSON.");
      return;
    }
    await updateEntry(entry.id, { value: parsed });
    setEditing(false);
    setEditError("");
  };

  const valueStr = JSON.stringify(entry.value, null, 0);
  const displayValue =
    valueStr.length > 80 ? valueStr.slice(0, 77) + "…" : valueStr;

  return (
    <div className={`memory-entry${entry.pinned ? " memory-entry--pinned" : ""}`}>
      <div className="memory-entry__header">
        {/* Pin button */}
        <button
          className={`memory-pin-btn${entry.pinned ? " memory-pin-btn--active" : ""}`}
          title={entry.pinned ? "Unpin" : "Pin"}
          onClick={() => pinEntry(entry.id, !entry.pinned)}
          aria-label={entry.pinned ? "Unpin entry" : "Pin entry"}
        >
          📌
        </button>

        <div className="memory-entry__meta">
          <span className="memory-entry__key">{entry.key}</span>
          <span className="memory-entry__source">
            {sourceLabels[entry.source] ?? entry.source}
          </span>

          {/* Confidence bar */}
          <span className="memory-conf-bar" title={`${Math.round(entry.confidence * 100)}% confidence`}>
            <span
              className="memory-conf-fill"
              style={{ width: `${Math.round(entry.confidence * 100)}%` }}
            />
          </span>
        </div>

        <div className="memory-entry__actions">
          <button
            className="mem-btn mem-btn--icon"
            title="Edit"
            onClick={() => { setEditing((v) => !v); setEditRaw(JSON.stringify(entry.value, null, 2)); }}
          >
            ✏️
          </button>
          <button
            className="mem-btn mem-btn--icon mem-btn--danger"
            title="Delete"
            onClick={() => deleteEntry(entry.id)}
          >
            🗑
          </button>
        </div>
      </div>

      {!editing && (
        <pre className="memory-entry__value">{displayValue}</pre>
      )}

      {editing && (
        <div className="memory-entry__edit">
          <textarea
            className="memory-form__input memory-form__textarea"
            value={editRaw}
            onChange={(e) => { setEditRaw(e.target.value); setEditError(""); }}
            rows={4}
          />
          {editError && <span className="memory-form__error">{editError}</span>}
          <div className="memory-form__actions">
            <button className="mem-btn mem-btn--primary" onClick={handleSave}>Save</button>
            <button className="mem-btn mem-btn--ghost" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Category group ────────────────────────────────────────────────────────────

interface CategoryGroupProps {
  category: MemoryCategory;
  entries: MemoryEntry[];
}

const CategoryGroup: React.FC<CategoryGroupProps> = ({ category, entries }) => {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  if (entries.length === 0) return null;

  const categoryLabels: Record<string, string> = {
    user_preferences:     t("memory", "category_user_preferences"),
    workflow_preferences: t("memory", "category_workflow_preferences"),
    task_history:         t("memory", "category_task_history"),
    suggestions:          t("memory", "category_suggestions"),
  };

  return (
    <section className="memory-category">
      <button
        className="memory-section-title memory-section-title--btn"
        onClick={() => setCollapsed((v) => !v)}
      >
        {categoryLabels[category] ?? category}
        <span className="memory-count">{entries.length}</span>
        <span className="memory-chevron">{collapsed ? "▶" : "▼"}</span>
      </button>
      {!collapsed && (
        <div className="memory-category__entries">
          {entries.map((e) => (
            <EntryRow key={e.id} entry={e} />
          ))}
        </div>
      )}
    </section>
  );
};

// ─── Page ──────────────────────────────────────────────────────────────────────

export const MemoryPage: React.FC = () => {
  const { entries, isLoading, error, fetchEntries, fetchSuggestions } =
    useMemoryStore();
  const { t } = useI18n();
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    fetchEntries();
    fetchSuggestions();
  }, []);

  // Group entries by category
  const grouped = ORDERED_CATEGORIES.reduce<Record<string, MemoryEntry[]>>(
    (acc, cat) => {
      acc[cat] = entries.filter((e) => e.category === cat);
      return acc;
    },
    {}
  );

  const totalActive = entries.length;

  return (
    <div className="page memory-page">
      <div className="memory-page__header">
        <div>
          <h1>{t("memory", "title")}</h1>
          <p className="memory-page__subtitle">
            {totalActive} {t("memory", "no_entries")}
          </p>
        </div>
        <button
          className="mem-btn mem-btn--primary"
          onClick={() => setShowAdd((v) => !v)}
        >
          {showAdd ? `✖ ${t("common", "close")}` : t("memory", "add_entry")}
        </button>
      </div>

      {error && <p className="memory-error">{error}</p>}

      {showAdd && <AddEntryForm onClose={() => setShowAdd(false)} />}

      {isLoading ? (
        <p className="memory-loading">{t("common", "loading")}</p>
      ) : (
        <>
          <SuggestionCards />

          {ORDERED_CATEGORIES.map((cat) => (
            <CategoryGroup
              key={cat}
              category={cat}
              entries={grouped[cat] ?? []}
            />
          ))}

          {totalActive === 0 && !isLoading && (
            <div className="memory-empty">
              <p>{t("memory", "no_entries")}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default MemoryPage;
