import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
});

// Auth interceptor
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('scada-studio-token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Config endpoints
export const configApi = {
  upload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/configs/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  list: () => api.get('/configs'),
  get: (id: string) => api.get(`/configs/${id}`),
  remove: (id: string) => api.delete(`/configs/${id}`),
  getPoints: (id: string) => api.get(`/configs/${id}/points`),
  getDevices: (id: string) => api.get(`/configs/${id}/devices`),
  getXml: (id: string) => api.get(`/configs/${id}/xml`),
  generatePoints: (id: string) => api.post(`/configs/${id}/generate-points`),
};

// Query endpoints
export const queryApi = {
  search: (query: string) => api.post('/query/search', { query }),
  cimTopology: (query: string) => api.post('/query/cim-topology', { query }),
  sparql: (sparql: string) => api.post('/query/cim-topology', { sparql }),
};

// Repo endpoints
export const repoApi = {
  list: () => api.get('/repos'),
  create: (name: string, description?: string) => api.post('/repos', { name, description }),
  get: (owner: string, name: string) => api.get(`/repos/${owner}/${name}`),
  getFiles: (owner: string, name: string) => api.get(`/repos/${owner}/${name}/files`),
  getCommits: (owner: string, name: string) => api.get(`/repos/${owner}/${name}/commits`),
  commit: (owner: string, name: string, files: any[], message: string) =>
    api.post(`/repos/${owner}/${name}/commit`, { files, message }),
};

// Diff endpoints
export const diffApi = {
  compare: (xml1: string, xml2: string, label1?: string, label2?: string) =>
    api.post('/diff/compare', { xml1, xml2, label1, label2 }),
};

// Settings endpoints
export const settingsApi = {
  getGitea: () => api.get('/settings/gitea'),
  updateGitea: (config: { url?: string; token?: string; username?: string }) =>
    api.post('/settings/gitea', config),
};

export default api;
