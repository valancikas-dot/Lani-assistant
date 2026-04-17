/**
 * Builder store – Zustand state for Builder Mode.
 *
 * Manages the lifecycle of a builder task:
 *   goal input → task submission → result display → file tree / commands
 */

import { create } from "zustand";
import {
  runBuilderTask,
  getProjectTree,
  generateFeatureFiles,
  proposeCommands,
} from "../lib/api";
import type {
  BuilderTaskResponse,
  GeneratedFile,
  ProposedCommand,
  ProjectTemplate,
  ProjectTreeNode,
  FeatureFilesRequest,
  ProposeCommandsRequest,
} from "../lib/types";

// ─── State ────────────────────────────────────────────────────────────────────

export interface BuilderState {
  // Inputs
  goal: string;
  template: ProjectTemplate;
  projectName: string;
  baseDir: string;
  features: string[];

  // Results
  taskResult: BuilderTaskResponse | null;
  files: GeneratedFile[];
  commands: ProposedCommand[];
  treeRoot: ProjectTreeNode | null;

  // Status
  loading: boolean;
  treeLoading: boolean;
  error: string | null;
  success: string | null;

  // Actions
  setGoal: (goal: string) => void;
  setTemplate: (template: ProjectTemplate) => void;
  setProjectName: (name: string) => void;
  setBaseDir: (dir: string) => void;
  setFeatures: (features: string[]) => void;
  addFeature: (feature: string) => void;
  removeFeature: (feature: string) => void;

  submitTask: () => Promise<void>;
  loadTree: (projectPath: string, maxDepth?: number) => Promise<void>;
  loadFeatureFiles: (req: FeatureFilesRequest) => Promise<void>;
  loadCommands: (req: ProposeCommandsRequest) => Promise<void>;

  reset: () => void;
  clearError: () => void;
}

// ─── Initial values ───────────────────────────────────────────────────────────

const INIT = {
  goal: "",
  template: "generic" as ProjectTemplate,
  projectName: "",
  baseDir: "",
  features: [] as string[],
  taskResult: null,
  files: [] as GeneratedFile[],
  commands: [] as ProposedCommand[],
  treeRoot: null,
  loading: false,
  treeLoading: false,
  error: null,
  success: null,
};

// ─── Store ────────────────────────────────────────────────────────────────────

export const useBuilderStore = create<BuilderState>((set, get) => ({
  ...INIT,

  setGoal: (goal) => set({ goal }),
  setTemplate: (template) => set({ template }),
  setProjectName: (projectName) => set({ projectName }),
  setBaseDir: (baseDir) => set({ baseDir }),
  setFeatures: (features) => set({ features }),
  addFeature: (feature) => {
    const f = feature.trim();
    if (f && !get().features.includes(f)) {
      set((s) => ({ features: [...s.features, f] }));
    }
  },
  removeFeature: (feature) =>
    set((s) => ({ features: s.features.filter((x) => x !== feature) })),

  submitTask: async () => {
    const { goal, template, projectName, baseDir, features } = get();
    if (!goal.trim()) return;

    set({ loading: true, error: null, success: null, taskResult: null });
    try {
      const result = await runBuilderTask({
        goal,
        template: template === "generic" ? undefined : template,
        project_name: projectName.trim() || undefined,
        base_dir: baseDir.trim() || undefined,
        features,
      });

      set({
        taskResult: result,
        commands: result.proposed_commands,
        success: result.ok ? result.summary : null,
        error: result.ok ? null : result.summary,
      });

      // Auto-load the file tree
      if (result.ok && result.project_path) {
        await get().loadTree(result.project_path);
      }
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ loading: false });
    }
  },

  loadTree: async (projectPath, maxDepth = 4) => {
    set({ treeLoading: true });
    try {
      const resp = await getProjectTree(projectPath, maxDepth);
      set({ treeRoot: resp.ok ? resp.root : null });
    } catch {
      // Tree load failures are non-fatal
      set({ treeRoot: null });
    } finally {
      set({ treeLoading: false });
    }
  },

  loadFeatureFiles: async (req) => {
    set({ loading: true, error: null });
    try {
      const resp = await generateFeatureFiles(req);
      if (resp.ok) {
        set((s) => ({
          files: [
            ...s.files,
            ...resp.files.filter(
              (f) => !s.files.some((x) => x.path === f.path)
            ),
          ],
          success: resp.message,
        }));
      } else {
        set({ error: resp.message });
      }
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ loading: false });
    }
  },

  loadCommands: async (req) => {
    set({ loading: true });
    try {
      const resp = await proposeCommands(req);
      if (resp.ok) {
        set({ commands: resp.commands });
      }
    } catch {
      /* non-fatal */
    } finally {
      set({ loading: false });
    }
  },

  reset: () => set({ ...INIT }),
  clearError: () => set({ error: null }),
}));
