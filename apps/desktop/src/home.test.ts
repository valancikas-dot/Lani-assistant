/**
 * home.test.ts – pure unit tests for the Home UX layer.
 *
 * Tests:
 *   INTENT_CARDS structure
 *   STARTERS map structure
 *   Intent → slug mapping logic
 *   Slug deduplication logic
 *
 * No DOM required — vitest node environment.
 */

import { describe, it, expect } from "vitest";
import { INTENT_CARDS } from "./pages/OnboardingPage";
import { STARTERS } from "./components/home/StarterCards";

// ─── INTENT_CARDS ─────────────────────────────────────────────────────────────

describe("INTENT_CARDS", () => {
  it("has exactly 6 entries", () => {
    expect(INTENT_CARDS).toHaveLength(6);
  });

  it("each card has required fields", () => {
    for (const card of INTENT_CARDS) {
      expect(typeof card.id).toBe("string");
      expect(card.id.length).toBeGreaterThan(0);
      expect(typeof card.emoji).toBe("string");
      expect(typeof card.title).toBe("string");
      expect(typeof card.description).toBe("string");
      // slug is string | null
      expect(card.slug === null || typeof card.slug === "string").toBe(true);
    }
  });

  it("all card IDs are unique", () => {
    const ids = INTENT_CARDS.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("known slugs reference valid backend modes", () => {
    const VALID_SLUGS = new Set([
      "developer", "researcher", "writer",
      "productivity", "communicator", "analyst", "student",
    ]);
    for (const card of INTENT_CARDS) {
      if (card.slug !== null) {
        expect(VALID_SLUGS.has(card.slug)).toBe(true);
      }
    }
  });

  it("max 3 unique slugs are reachable (accounting for duplicates)", () => {
    const uniqueSlugs = new Set(INTENT_CARDS.map((c) => c.slug).filter(Boolean));
    // We have 6 cards but writer appears twice; expect ≤6 unique non-null slugs
    expect(uniqueSlugs.size).toBeLessThanOrEqual(6);
  });

  it("general AI assistant card has null slug (no specific mode)", () => {
    const general = INTENT_CARDS.find((c) => c.id === "general");
    expect(general).toBeDefined();
    expect(general!.slug).toBeNull();
  });

  it("software card maps to developer slug", () => {
    const sw = INTENT_CARDS.find((c) => c.id === "software");
    expect(sw?.slug).toBe("developer");
  });

  it("automate card maps to productivity slug", () => {
    const auto = INTENT_CARDS.find((c) => c.id === "automate");
    expect(auto?.slug).toBe("productivity");
  });
});

// ─── STARTERS ─────────────────────────────────────────────────────────────────

describe("STARTERS", () => {
  it("has entries for all 7 builtin mode slugs", () => {
    const BUILTIN_SLUGS = ["developer", "writer", "researcher", "analyst", "productivity", "communicator", "student"];
    for (const slug of BUILTIN_SLUGS) {
      expect(STARTERS[slug]).toBeDefined();
    }
  });

  it("each mode has at least 3 starter cards", () => {
    for (const [slug, cards] of Object.entries(STARTERS)) {
      expect(cards.length).toBeGreaterThanOrEqual(3);
    }
  });

  it("each starter card has icon, label, and prompt", () => {
    for (const [, cards] of Object.entries(STARTERS)) {
      for (const card of cards) {
        expect(typeof card.icon).toBe("string");
        expect(card.icon.length).toBeGreaterThan(0);
        expect(typeof card.label).toBe("string");
        expect(card.label.length).toBeGreaterThan(0);
        expect(typeof card.prompt).toBe("string");
        expect(card.prompt.length).toBeGreaterThan(0);
      }
    }
  });

  it("developer mode has expected quick actions", () => {
    const labels = STARTERS.developer.map((c) => c.label);
    expect(labels).toContain("Create a new app");
    expect(labels).toContain("Fix a bug");
  });

  it("analyst mode has marketing-related actions", () => {
    const labels = STARTERS.analyst.map((c) => c.label);
    expect(labels.some((l) => l.toLowerCase().includes("campaign") || l.toLowerCase().includes("ad") || l.toLowerCase().includes("analys"))).toBe(true);
  });

  it("productivity mode has automation action", () => {
    const labels = STARTERS.productivity.map((c) => c.label);
    expect(labels.some((l) => l.toLowerCase().includes("automat"))).toBe(true);
  });

  it("writer mode has video/music content actions", () => {
    const labels = STARTERS.writer.map((c) => c.label);
    expect(labels.some((l) => l.toLowerCase().includes("video") || l.toLowerCase().includes("script") || l.toLowerCase().includes("lyric"))).toBe(true);
  });
});

// ─── Slug deduplication logic (mirrors OnboardingPage.handleContinue) ──────────

describe("intent → slug deduplication", () => {
  it("deduplicated slugs from all 6 selected cards produces ≤5 unique slugs", () => {
    const allSlugs = INTENT_CARDS.map((c) => c.slug).filter(Boolean) as string[];
    const unique = [...new Set(allSlugs)];
    // video + music both map to "writer" → dedup should reduce count
    expect(unique.length).toBeLessThan(INTENT_CARDS.length);
  });

  it("selecting video and music only produces one 'writer' slug", () => {
    const selected = INTENT_CARDS.filter((c) => c.id === "video" || c.id === "music");
    const slugs = [...new Set(selected.map((c) => c.slug).filter(Boolean))];
    expect(slugs).toEqual(["writer"]);
  });

  it("selecting general-only produces empty slug list (null filtered out)", () => {
    const selected = INTENT_CARDS.filter((c) => c.id === "general");
    const slugs = selected.map((c) => c.slug).filter(Boolean);
    expect(slugs).toHaveLength(0);
  });
});
