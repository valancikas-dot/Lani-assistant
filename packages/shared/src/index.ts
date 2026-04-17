/**
 * Shared contract types – single source of truth for both
 * the TypeScript frontend and the Python backend schemas.
 *
 * These types are intentionally minimal; the canonical Python
 * versions live in services/orchestrator/app/schemas/.
 */

// Re-export everything from the desktop lib/types for convenience
export * from "../../apps/desktop/src/lib/types";
