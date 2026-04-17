/**
 * ProfilesPage – Phase 10: Multi-profile / Team Mode
 *
 * Displays all profiles as cards.  The active profile is highlighted.
 * Users can create, activate, edit, and archive profiles.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  listProfiles,
  createProfile,
  activateProfile,
  archiveProfile,
  updateProfile,
} from "../lib/api";
import type {
  Profile,
  ProfileType,
  SecurityMode,
  CreateProfileRequest,
  UpdateProfileRequest,
} from "../lib/types";
import { useI18n } from "../i18n/useI18n";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface CreateFormState {
  name: string;
  profile_type: ProfileType;
  description: string;
  default_security_mode: SecurityMode;
  activate: boolean;
}

const EMPTY_FORM: CreateFormState = {
  name: "",
  profile_type: "personal",
  description: "",
  default_security_mode: "standard",
  activate: false,
};

// ─── Component ────────────────────────────────────────────────────────────────

export const ProfilesPage: React.FC = () => {
  const { t } = useI18n();

  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateFormState>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<UpdateProfileRequest>({});
  const [saving, setSaving] = useState(false);

  const [confirmArchive, setConfirmArchive] = useState<number | null>(null);

  // ── Fetch ──────────────────────────────────────────────────────────────────

  const fetchProfiles = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listProfiles();
      setProfiles(res.profiles);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load profiles");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchProfiles();
  }, [fetchProfiles]);

  // ── Create ─────────────────────────────────────────────────────────────────

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const payload: CreateProfileRequest = {
        name: form.name.trim(),
        profile_type: form.profile_type,
        description: form.description,
        default_security_mode: form.default_security_mode,
        activate: form.activate,
      };
      await createProfile(payload);
      setForm(EMPTY_FORM);
      setShowCreate(false);
      await fetchProfiles();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create profile");
    } finally {
      setCreating(false);
    }
  };

  // ── Activate ───────────────────────────────────────────────────────────────

  const handleActivate = async (profileId: number) => {
    setError(null);
    try {
      await activateProfile(profileId);
      await fetchProfiles();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to activate profile");
    }
  };

  // ── Edit / Save ────────────────────────────────────────────────────────────

  const startEdit = (profile: Profile) => {
    setEditingId(profile.id);
    setEditForm({
      name: profile.name,
      description: profile.description,
      default_security_mode: profile.default_security_mode,
    });
  };

  const handleSave = async (profileId: number) => {
    setSaving(true);
    setError(null);
    try {
      await updateProfile(profileId, editForm);
      setEditingId(null);
      await fetchProfiles();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update profile");
    } finally {
      setSaving(false);
    }
  };

  // ── Archive ────────────────────────────────────────────────────────────────

  const handleArchive = async (profileId: number) => {
    setError(null);
    try {
      await archiveProfile(profileId);
      setConfirmArchive(null);
      await fetchProfiles();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to archive profile");
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="page profiles-page">
      <div className="page__header">
        <h1>{t("profiles", "title")}</h1>
        <p className="page__subtitle">{t("profiles", "subtitle")}</p>
        <button
          className="btn btn--primary"
          onClick={() => setShowCreate((v) => !v)}
        >
          {showCreate ? t("common", "cancel") : t("profiles", "new_profile")}
        </button>
      </div>

      {error && <div className="page__error">{error}</div>}

      {/* ── Create form ────────────────────────────────────────────────────── */}
      {showCreate && (
        <form className="profiles-page__create-form card" onSubmit={handleCreate}>
          <h2>{t("profiles", "new_profile")}</h2>

          <label className="form-field">
            <span>{t("profiles", "name")}</span>
            <input
              type="text"
              value={form.name}
              maxLength={120}
              required
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </label>

          <label className="form-field">
            <span>{t("profiles", "type")}</span>
            <select
              value={form.profile_type}
              onChange={(e) =>
                setForm((f) => ({ ...f, profile_type: e.target.value as ProfileType }))
              }
            >
              <option value="personal">{t("profiles", "type_personal")}</option>
              <option value="work">{t("profiles", "type_work")}</option>
              <option value="team">{t("profiles", "type_team")}</option>
            </select>
          </label>

          <label className="form-field">
            <span>{t("profiles", "security_mode")}</span>
            <select
              value={form.default_security_mode}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  default_security_mode: e.target.value as SecurityMode,
                }))
              }
            >
              <option value="standard">{t("profiles", "security_standard")}</option>
              <option value="strict">{t("profiles", "security_strict")}</option>
              <option value="permissive">{t("profiles", "security_permissive")}</option>
            </select>
          </label>

          <label className="form-field">
            <span>{t("profiles", "description")}</span>
            <textarea
              value={form.description}
              rows={2}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </label>

          <label className="form-field form-field--checkbox">
            <input
              type="checkbox"
              checked={form.activate}
              onChange={(e) => setForm((f) => ({ ...f, activate: e.target.checked }))}
            />
            <span>{t("profiles", "activate_on_create")}</span>
          </label>

          <div className="form-actions">
            <button type="submit" className="btn btn--primary" disabled={creating}>
              {creating ? t("common", "saving") : t("common", "create")}
            </button>
          </div>
        </form>
      )}

      {/* ── Profile list ───────────────────────────────────────────────────── */}
      {isLoading && profiles.length === 0 ? (
        <p className="page__loading">{t("common", "loading")}</p>
      ) : profiles.length === 0 ? (
        <div className="page__empty">
          <p>{t("profiles", "no_profiles")}</p>
        </div>
      ) : (
        <div className="profiles-page__grid">
          {profiles.map((profile) => (
            <div
              key={profile.id}
              className={[
                "profiles-page__card card",
                profile.is_active ? "profiles-page__card--active" : "",
                profile.status === "archived" ? "profiles-page__card--archived" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {/* ── Card header ──────────────────────────────────────────── */}
              <div className="profiles-page__card-header">
                {editingId === profile.id ? (
                  <input
                    className="profiles-page__name-input"
                    value={editForm.name ?? ""}
                    maxLength={120}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, name: e.target.value }))
                    }
                  />
                ) : (
                  <h3 className="profiles-page__name">
                    {profile.name}
                    {profile.is_active && (
                      <span className="profiles-page__active-badge">
                        {t("profiles", "active")}
                      </span>
                    )}
                  </h3>
                )}
                <span className="profiles-page__type-badge">
                  {profile.profile_type}
                </span>
              </div>

              {/* ── Description ──────────────────────────────────────────── */}
              {editingId === profile.id ? (
                <textarea
                  className="profiles-page__desc-input"
                  value={editForm.description ?? ""}
                  rows={2}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, description: e.target.value }))
                  }
                />
              ) : (
                profile.description && (
                  <p className="profiles-page__description">{profile.description}</p>
                )
              )}

              {/* ── Security mode ─────────────────────────────────────────── */}
              {editingId === profile.id ? (
                <label className="form-field">
                  <span>{t("profiles", "security_mode")}</span>
                  <select
                    value={editForm.default_security_mode ?? profile.default_security_mode}
                    onChange={(e) =>
                      setEditForm((f) => ({
                        ...f,
                        default_security_mode: e.target.value as SecurityMode,
                      }))
                    }
                  >
                    <option value="standard">{t("profiles", "security_standard")}</option>
                    <option value="strict">{t("profiles", "security_strict")}</option>
                    <option value="permissive">{t("profiles", "security_permissive")}</option>
                  </select>
                </label>
              ) : (
                <p className="profiles-page__meta">
                  {t("profiles", "security_mode")}:{" "}
                  <strong>{profile.default_security_mode}</strong>
                </p>
              )}

              {/* ── Stats ────────────────────────────────────────────────── */}
              {profile.stats && (
                <div className="profiles-page__stats">
                  <span>{t("profiles", "stat_missions")}: {profile.stats.missions}</span>
                  <span>{t("profiles", "stat_skills")}: {profile.stats.installed_skills}</span>
                  <span>{t("profiles", "stat_proposals")}: {profile.stats.skill_proposals}</span>
                </div>
              )}

              {/* ── Actions ──────────────────────────────────────────────── */}
              <div className="profiles-page__actions">
                {editingId === profile.id ? (
                  <>
                    <button
                      className="btn btn--primary btn--sm"
                      disabled={saving}
                      onClick={() => void handleSave(profile.id)}
                    >
                      {saving ? t("common", "saving") : t("common", "save")}
                    </button>
                    <button
                      className="btn btn--sm"
                      onClick={() => setEditingId(null)}
                    >
                      {t("common", "cancel")}
                    </button>
                  </>
                ) : (
                  <>
                    {!profile.is_active && profile.status !== "archived" && (
                      <button
                        className="btn btn--sm btn--secondary"
                        onClick={() => void handleActivate(profile.id)}
                      >
                        {t("profiles", "activate")}
                      </button>
                    )}
                    {profile.status !== "archived" && (
                      <button
                        className="btn btn--sm"
                        onClick={() => startEdit(profile)}
                      >
                        {t("common", "edit")}
                      </button>
                    )}
                    {profile.status !== "archived" && (
                      confirmArchive === profile.id ? (
                        <>
                          <button
                            className="btn btn--sm btn--danger"
                            onClick={() => void handleArchive(profile.id)}
                          >
                            {t("common", "confirm")}
                          </button>
                          <button
                            className="btn btn--sm"
                            onClick={() => setConfirmArchive(null)}
                          >
                            {t("common", "cancel")}
                          </button>
                        </>
                      ) : (
                        <button
                          className="btn btn--sm btn--ghost"
                          onClick={() => setConfirmArchive(profile.id)}
                        >
                          {t("profiles", "archive")}
                        </button>
                      )
                    )}
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
