/**
 * VoiceEnrollmentPanel – balso profilio užregistravimas tiesiogiai mikrofonu.
 *
 * Žingsniai:
 *   1. Spustelėk "Pradėti" → backend sukuria enrollment sesiją
 *   2. Įrašyk 3 fragmentus (kiekvieną ~3-5 s) su 🔴 mygtuku
 *   3. Spustelėk "Baigti" → backend apskaičiuoja fingerprint
 *   4. Nuo šiol Lani reaguoja tik į tavo balsą
 */

import React, { useState, useRef, useCallback, useEffect } from "react";
import * as api from "../../lib/api";

// ── Tipai ──────────────────────────────────────────────────────────────────────

type PanelState =
  | "loading"       // tikrina profilį
  | "no_profile"    // nėra profilio
  | "enrolled"      // profilis užregistruotas
  | "enrolling"     // enrollment sesija aktyvi
  | "recording"     // mikrofonas įjungtas
  | "uploading"     // siunčiamas mėginys
  | "error";

interface VoiceProfileInfo {
  id: number;
  enrollment_status: string;
  sample_count: number;
  verification_enabled: boolean;
  last_verified_at?: string | null;
}

// ── Pagalbinės funkcijos ───────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "enrolled"
      ? "#10b981"
      : status === "enrolling" || status === "enrollment_incomplete"
        ? "#f59e0b"
        : "#6b7280";
  const label =
    status === "enrolled"
      ? "✓ Užregistruotas"
      : status === "enrolling"
        ? "⏳ Registruojama…"
        : status === "enrollment_incomplete"
          ? "⚠ Neužbaigta (reikia 3+ mėginių)"
          : "✗ Neužregistruotas";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: "12px",
        background: `${color}22`,
        border: `1px solid ${color}55`,
        color,
        fontSize: "12px",
        fontWeight: 600,
      }}
    >
      {label}
    </span>
  );
}

// ── Pagrindinis komponentas ────────────────────────────────────────────────────

export const VoiceEnrollmentPanel: React.FC = () => {
  const [state, setState] = useState<PanelState>("loading");
  const [profile, setProfile] = useState<VoiceProfileInfo | null>(null);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [samplesRecorded, setSamplesRecorded] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [messageColor, setMessageColor] = useState<string>("#6b7280");

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const showMsg = (text: string, color = "#6b7280") => {
    setMessage(text);
    setMessageColor(color);
  };

  // ── Įkeliame profilio būseną ──────────────────────────────────────────────

  const loadProfile = useCallback(async () => {
    setState("loading");
    try {
      const p = await api.getVoiceProfile() as VoiceProfileInfo;
      setProfile(p);
      if (p.enrollment_status === "enrolled") {
        setState("enrolled");
      } else if (p.enrollment_status === "enrolling" || p.enrollment_status === "enrollment_incomplete") {
        setProfileId(p.id);
        setSamplesRecorded(p.sample_count ?? 0);
        setState("enrolling");
        showMsg("Enrollment sesija aktyvi — įrašyk dar mėginių.", "#f59e0b");
      } else {
        setState("no_profile");
      }
    } catch {
      setState("no_profile");
      setProfile(null);
    }
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  // ── Pradedame enrollment ──────────────────────────────────────────────────

  const handleStart = async () => {
    try {
      showMsg("Pradedama enrollment sesija…", "#3b82f6");
      const res = await api.enrollStart("Primary") as { profile_id: number };
      setProfileId(res.profile_id);
      setSamplesRecorded(0);
      setState("enrolling");
      showMsg('Sesija sukurta! Įrašyk 3 balso fragmentus (pvz. pasakyk "Sveika Lani, atidaryk terminalą").', "#10b981");
    } catch (err: any) {
      showMsg(`Klaida: ${String(err)}`, "#ef4444");
    }
  };

  // ── Pradedame įrašymą ─────────────────────────────────────────────────────

  const handleStartRecording = async () => {
    if (!profileId) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.start(100);
      setState("recording");
      showMsg("🔴 Įrašoma… pasakyk keletą sakinių natūraliai (3–5 sekundės), tada spustelėk Sustabdyti.", "#ef4444");
    } catch (err) {
      showMsg("Nepavyko pasiekti mikrofono. Patikrinkite leidimus Sistemos nustatymuose → Privatumas → Mikrofonas.", "#ef4444");
    }
  };

  // ── Sustabdome įrašymą ir siunčiame ──────────────────────────────────────

  const handleStopRecording = async () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || !profileId) return;

    setState("uploading");
    showMsg("⏳ Siunčiamas mėginys…", "#3b82f6");

    // Sustabdome recorder, gauname chunks
    await new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
      recorder.stop();
    });

    // Sustabdome mikrofono srautą
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;

    if (chunksRef.current.length === 0) {
      setState("enrolling");
      showMsg("Nepavyko įrašyti garso. Bandykite dar kartą.", "#ef4444");
      return;
    }

    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    chunksRef.current = [];

    try {
      await api.enrollSample(blob, profileId);
      const newCount = samplesRecorded + 1;
      setSamplesRecorded(newCount);
      setState("enrolling");

      if (newCount >= 3) {
        showMsg(`✓ ${newCount} mėginiai įrašyti. Galite baigti enrollment arba įrašyti daugiau (rekomenduojama 5).`, "#10b981");
      } else {
        showMsg(`✓ Mėginys ${newCount}/3 įrašytas. Reikia dar ${3 - newCount}.`, "#f59e0b");
      }
    } catch (err: any) {
      setState("enrolling");
      showMsg(`Klaida siunčiant mėginį: ${String(err)}`, "#ef4444");
    }
  };

  // ── Baigiame enrollment ───────────────────────────────────────────────────

  const handleFinish = async () => {
    if (!profileId) return;
    if (samplesRecorded < 3) {
      showMsg(`Reikia bent 3 mėginių. Šiuo metu: ${samplesRecorded}.`, "#ef4444");
      return;
    }

    try {
      showMsg("⏳ Apskaičiuojamas jūsų balso profilis…", "#3b82f6");
      const result = await api.enrollFinish(profileId) as { enrollment_status: string };

      if (result.enrollment_status === "enrolled") {
        showMsg("✓ Balso profilis sėkmingai užregistruotas! Nuo šiol Lani reaguos tik į jūsų balsą.", "#10b981");
        setState("enrolled");
        await loadProfile();
      } else {
        showMsg(`Enrollment neužbaigtas: ${result.enrollment_status}. Gali reikėti daugiau mėginių.`, "#f59e0b");
        setState("enrolling");
      }
    } catch (err: any) {
      showMsg(`Klaida: ${String(err)}`, "#ef4444");
      setState("enrolling");
    }
  };

  // ── Ištriname profilį ─────────────────────────────────────────────────────

  const handleDelete = async () => {
    if (!confirm("Ar tikrai norite ištrinti balso profilį? Lani nebebus atpažįstama jūsų balsas.")) return;
    try {
      await api.deleteVoiceProfile();
      setProfile(null);
      setProfileId(null);
      setSamplesRecorded(0);
      setState("no_profile");
      showMsg("Balso profilis ištrintas.", "#6b7280");
    } catch (err: any) {
      showMsg(`Klaida: ${String(err)}`, "#ef4444");
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  const sectionStyle: React.CSSProperties = {
    background: "rgba(255,255,255,0.03)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: "10px",
    padding: "16px 20px",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  };

  const btnStyle = (color: string, disabled = false): React.CSSProperties => ({
    padding: "8px 18px",
    borderRadius: "8px",
    border: `1px solid ${color}66`,
    background: `${color}18`,
    color: disabled ? "#6b7280" : color,
    fontWeight: 600,
    fontSize: "13px",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
  });

  if (state === "loading") {
    return (
      <div style={sectionStyle}>
        <span style={{ color: "#6b7280", fontSize: "13px" }}>⏳ Kraunama…</span>
      </div>
    );
  }

  return (
    <div style={sectionStyle}>
      {/* Antraštė */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0, fontSize: "15px" }}>🎙 Balso atpažinimas</h3>
        {profile && <StatusBadge status={profile.enrollment_status ?? "not_configured"} />}
      </div>

      {/* Aprašymas */}
      <p style={{ margin: 0, fontSize: "13px", color: "#9ca3af", lineHeight: 1.5 }}>
        Užregistruok savo balsą — Lani reaguos <strong>tik į tavo balsą</strong> ir ignoruos
        fone esančius žmones, televizorių ar kitus šaltinius.
      </p>

      {/* ── Būsena: enrolled ── */}
      {state === "enrolled" && profile && (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <div style={{ fontSize: "13px", color: "#d1d5db" }}>
            <span>📊 Mėginių: <strong>{profile.sample_count}</strong></span>
            {profile.last_verified_at && (
              <span style={{ marginLeft: "16px" }}>
                🕐 Paskutinis atpažinimas: <strong>{new Date(profile.last_verified_at).toLocaleString("lt-LT")}</strong>
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button style={btnStyle("#f59e0b")} onClick={() => void handleStart()}>
              🔄 Perkalibruoti
            </button>
            <button style={btnStyle("#ef4444")} onClick={() => void handleDelete()}>
              🗑 Ištrinti profilį
            </button>
          </div>
          <p style={{ margin: 0, fontSize: "12px", color: "#6b7280" }}>
            Jei Lani nebeatpažįsta jūsų balso — perkalibruokite (įrašykite naujus mėginius).
          </p>
        </div>
      )}

      {/* ── Būsena: no_profile → pradėti ── */}
      {state === "no_profile" && (
        <button style={btnStyle("#10b981")} onClick={() => void handleStart()}>
          ▶ Pradėti balso registraciją
        </button>
      )}

      {/* ── Būsena: enrolling / recording / uploading ── */}
      {(state === "enrolling" || state === "recording" || state === "uploading") && (
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          {/* Progreso juosta */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "13px", color: "#d1d5db" }}>Mėginiai:</span>
            {[1, 2, 3, 4, 5].map((n) => (
              <div
                key={n}
                style={{
                  width: "28px",
                  height: "28px",
                  borderRadius: "50%",
                  border: "2px solid",
                  borderColor: n <= samplesRecorded ? "#10b981" : n === samplesRecorded + 1 ? "#3b82f6" : "rgba(255,255,255,0.1)",
                  background: n <= samplesRecorded ? "#10b98133" : "transparent",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "11px",
                  color: n <= samplesRecorded ? "#10b981" : "#6b7280",
                  fontWeight: 600,
                }}
              >
                {n <= samplesRecorded ? "✓" : n}
              </div>
            ))}
            <span style={{ fontSize: "12px", color: "#6b7280" }}>
              {samplesRecorded < 3 ? "(reikia 3 min.)" : "(rekomenduojama 5)"}
            </span>
          </div>

          {/* Patarimai ką kalbėti */}
          {state === "enrolling" && samplesRecorded < 3 && (
            <div style={{
              padding: "8px 12px",
              borderRadius: "6px",
              background: "rgba(59,130,246,0.08)",
              border: "1px solid rgba(59,130,246,0.2)",
              fontSize: "12px",
              color: "#93c5fd",
            }}>
              💡 Pavyzdžiai ką sakyti kiekvieno mėginio metu:<br />
              <em>&bdquo;Sveika Lani, atidaryk terminalą&ldquo;</em><br />
              <em>&bdquo;Lani, parodyk man orus šiandien&ldquo;</em><br />
              <em>&bdquo;Hey Lani, sukurk naują failą dokumentuose&ldquo;</em>
            </div>
          )}

          {/* Įrašymo mygtukai */}
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            {state === "enrolling" && (
              <button
                style={btnStyle("#ef4444")}
                onClick={() => void handleStartRecording()}
              >
                🔴 Įrašyti mėginį {samplesRecorded + 1}
              </button>
            )}

            {state === "recording" && (
              <button
                style={{ ...btnStyle("#ef4444"), animation: "lani-pulse 1s ease-in-out infinite" }}
                onClick={() => void handleStopRecording()}
              >
                ⏹ Sustabdyti įrašymą
              </button>
            )}

            {state === "uploading" && (
              <button style={btnStyle("#3b82f6", true)} disabled>
                ⏳ Siunčiama…
              </button>
            )}

            {state === "enrolling" && samplesRecorded >= 3 && (
              <button style={btnStyle("#10b981")} onClick={() => void handleFinish()}>
                ✓ Baigti ir išsaugoti
              </button>
            )}

            <button
              style={btnStyle("#6b7280")}
              onClick={() => void handleDelete()}
              disabled={state === "recording" || state === "uploading"}
            >
              ✗ Atšaukti
            </button>
          </div>
        </div>
      )}

      {/* Pranešimas */}
      {message && (
        <div style={{
          padding: "8px 12px",
          borderRadius: "6px",
          background: `${messageColor}11`,
          border: `1px solid ${messageColor}33`,
          color: messageColor,
          fontSize: "12px",
          lineHeight: 1.5,
        }}>
          {message}
        </div>
      )}
    </div>
  );
};
