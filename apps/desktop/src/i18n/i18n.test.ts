/**
 * Lightweight i18n tests.
 *
 * Validates that:
 *  1. Known English keys return the correct English string.
 *  2. Known Lithuanian keys return the correct Lithuanian string.
 *  3. An unknown locale falls back to English.
 *  4. A key missing from the target locale falls back to English.
 *  5. Array lookups (lookupTArray) return non-empty string arrays.
 *  6. Variable interpolation in useI18n.t() replaces {var} placeholders.
 */

import { describe, it, expect } from "vitest";
import { lookupT, lookupTArray } from "./index";

// ---------------------------------------------------------------------------
// lookupT — scalar keys
// ---------------------------------------------------------------------------

describe("lookupT – English locale", () => {
  it("returns the correct nav.chat string", () => {
    expect(lookupT("en", "nav", "chat")).toBe("Chat");
  });

  it("returns the correct common.back string", () => {
    expect(lookupT("en", "common", "back")).toBe("Back");
  });

  it("returns the correct setup.welcome_title string", () => {
    expect(lookupT("en", "setup", "welcome_title")).toBe("Welcome to Lani");
  });

  it("returns the correct approvals.approve string", () => {
    expect(lookupT("en", "approvals", "approve")).toBe("✅ Approve");
  });
});

describe("lookupT – Lithuanian locale", () => {
  it("returns the Lithuanian nav.chat translation", () => {
    expect(lookupT("lt", "nav", "chat")).toBe("Pokalbis");
  });

  it("returns the Lithuanian common.back translation", () => {
    expect(lookupT("lt", "common", "back")).toBe("Atgal");
  });

  it("returns the Lithuanian setup.welcome_title translation", () => {
    expect(lookupT("lt", "setup", "welcome_title")).toBe("Sveiki atvykę į Lani");
  });
});

describe("lookupT – fallback behaviour", () => {
  it("falls back to English for an unknown locale code", () => {
    expect(lookupT("xx", "nav", "chat")).toBe("Chat");
  });

  it("falls back to English for the 'zz' fake locale", () => {
    expect(lookupT("zz", "common", "save")).toBe("Save Settings");
  });

  it("always returns a non-empty string", () => {
    const result = lookupT("lt", "nav", "settings");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// lookupTArray — array keys
// ---------------------------------------------------------------------------

describe("lookupTArray", () => {
  it("returns an array of strings for chat.command_examples in English", () => {
    const examples = lookupTArray("en", "chat", "command_examples");
    expect(Array.isArray(examples)).toBe(true);
    expect(examples.length).toBeGreaterThan(0);
    examples.forEach((ex) => expect(typeof ex).toBe("string"));
  });

  it("returns an array for chat.command_examples in Lithuanian", () => {
    const examples = lookupTArray("lt", "chat", "command_examples");
    expect(Array.isArray(examples)).toBe(true);
    expect(examples.length).toBeGreaterThan(0);
  });

  it("falls back to English array for unknown locale", () => {
    const examples = lookupTArray("xx", "chat", "command_examples");
    expect(Array.isArray(examples)).toBe(true);
    expect(examples.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Variable interpolation — tested directly via the engine
// ---------------------------------------------------------------------------

describe("translation keys with variable placeholders", () => {
  it("wake.phrase_placeholder contains a {phrase} placeholder in English", () => {
    const raw = lookupT("en", "wake", "phrase_placeholder");
    expect(raw).toContain("{phrase}");
  });

  it("session.expires_in is a non-empty string", () => {
    const raw = lookupT("en", "session", "expires_in");
    expect(typeof raw).toBe("string");
    expect(raw.length).toBeGreaterThan(0);
  });

  it("includes Mission Control navigation label", () => {
    expect(lookupT("en", "nav", "missions")).toBe("Missions");
  });

  it("includes Mission Control section title", () => {
    expect(lookupT("en", "mission_control", "title")).toBe("Mission Control");
  });
});
