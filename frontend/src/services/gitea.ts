import { settingsApi, repoApi } from './api';

export const giteaClient = {
  getSettings: () => settingsApi.getGitea(),
  updateSettings: (config: { url?: string; token?: string; username?: string }) =>
    settingsApi.updateGitea(config),
  listRepos: () => repoApi.list(),
  createRepo: (name: string, description?: string) => repoApi.create(name, description),
};
