import { create } from 'zustand';

export interface ConfigSummary {
  id: string;
  filename: string;
  uploadedAt: string;
  devices: number;
  points: number;
}

interface AppState {
  configs: ConfigSummary[];
  selectedConfigId: string | null;
  loading: boolean;
  error: string | null;

  setConfigs: (configs: ConfigSummary[]) => void;
  addConfig: (config: ConfigSummary) => void;
  removeConfig: (id: string) => void;
  selectConfig: (id: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  configs: [],
  selectedConfigId: null,
  loading: false,
  error: null,

  setConfigs: (configs) => set({ configs }),
  addConfig: (config) => set((s) => ({ configs: [...s.configs, config] })),
  removeConfig: (id) => set((s) => ({ configs: s.configs.filter((c) => c.id !== id) })),
  selectConfig: (id) => set({ selectedConfigId: id }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}));
