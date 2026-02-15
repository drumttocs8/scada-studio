/**
 * Gitea API Service
 * Integrates with Gitea or any Git server compatible with the Gitea API.
 */

import axios, { AxiosInstance } from 'axios';

export interface GiteaConfig {
  url: string;
  token: string;
  username: string;
}

export interface GiteaRepo {
  id: number;
  name: string;
  full_name: string;
  description: string;
  html_url: string;
  clone_url: string;
  ssh_url: string;
  default_branch: string;
  updated_at: string;
}

export interface GiteaCommit {
  sha: string;
  message: string;
  author: { name: string; email: string; date: string };
  committer: { name: string; email: string; date: string };
}

let giteaConfig: GiteaConfig = {
  url: process.env.GITEA_URL || 'http://localhost:3000',
  token: process.env.GITEA_TOKEN || '',
  username: process.env.GITEA_USERNAME || 'scada',
};

function getClient(): AxiosInstance {
  return axios.create({
    baseURL: `${giteaConfig.url}/api/v1`,
    headers: {
      Authorization: giteaConfig.token ? `token ${giteaConfig.token}` : '',
      'Content-Type': 'application/json',
    },
    timeout: 30000,
  });
}

export const giteaService = {
  getConfig(): GiteaConfig {
    return { ...giteaConfig, token: giteaConfig.token ? '***' : '' };
  },

  updateConfig(config: Partial<GiteaConfig>) {
    giteaConfig = { ...giteaConfig, ...config };
  },

  async testConnection(): Promise<{ ok: boolean; version?: string; error?: string }> {
    try {
      const resp = await getClient().get('/version');
      return { ok: true, version: resp.data.version };
    } catch (err: any) {
      return { ok: false, error: err.message };
    }
  },

  async listRepos(): Promise<GiteaRepo[]> {
    const resp = await getClient().get(`/user/repos`, { params: { limit: 50 } });
    return resp.data;
  },

  async getRepo(owner: string, name: string): Promise<GiteaRepo> {
    const resp = await getClient().get(`/repos/${owner}/${name}`);
    return resp.data;
  },

  async createRepo(name: string, description = '', isPrivate = true): Promise<GiteaRepo> {
    const resp = await getClient().post('/user/repos', {
      name,
      description,
      private: isPrivate,
      auto_init: true,
      default_branch: 'main',
    });
    return resp.data;
  },

  async getCommits(owner: string, name: string, limit = 20): Promise<GiteaCommit[]> {
    const resp = await getClient().get(`/repos/${owner}/${name}/git/commits`, {
      params: { limit },
    });
    return resp.data;
  },

  async getFileContent(owner: string, name: string, filepath: string, ref = 'main'): Promise<string> {
    const resp = await getClient().get(`/repos/${owner}/${name}/raw/${filepath}`, {
      params: { ref },
    });
    return resp.data;
  },

  async getTree(owner: string, name: string, ref = 'main'): Promise<any[]> {
    const resp = await getClient().get(`/repos/${owner}/${name}/git/trees/${ref}`, {
      params: { recursive: true },
    });
    return resp.data.tree || [];
  },

  async createOrUpdateFile(
    owner: string,
    name: string,
    filepath: string,
    content: string,
    message: string,
    sha?: string
  ): Promise<any> {
    const payload: any = {
      content: Buffer.from(content).toString('base64'),
      message,
    };
    if (sha) payload.sha = sha;
    const method = sha ? 'put' : 'post';
    const resp = await getClient()[method](
      `/repos/${owner}/${name}/contents/${filepath}`,
      payload
    );
    return resp.data;
  },

  async getFileSha(owner: string, name: string, filepath: string): Promise<string | null> {
    try {
      const resp = await getClient().get(`/repos/${owner}/${name}/contents/${filepath}`);
      return resp.data.sha || null;
    } catch {
      return null;
    }
  },

  async getDiff(owner: string, name: string, sha: string): Promise<string> {
    const resp = await getClient().get(`/repos/${owner}/${name}/git/commits/${sha}`, {
      headers: { Accept: 'application/json' },
    });
    return resp.data;
  },
};
