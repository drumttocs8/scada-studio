import { api } from './api';

export const authService = {
  async login(username: string, password: string): Promise<string> {
    const resp = await api.post('/auth/login', { username, password });
    const { token } = resp.data;
    localStorage.setItem('scada-studio-token', token);
    return token;
  },

  logout() {
    localStorage.removeItem('scada-studio-token');
  },

  isAuthenticated(): boolean {
    return !!localStorage.getItem('scada-studio-token');
  },
};
