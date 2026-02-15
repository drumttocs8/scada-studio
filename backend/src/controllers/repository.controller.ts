import { Request, Response } from 'express';
import { giteaService } from '../services/gitea.service';
import { gitService } from '../services/git.service';

export const repositoryController = {
    async list(_req: Request, res: Response) {
        try {
            const repos = await giteaService.listRepos();
            return res.json(repos);
        } catch (err: any) {
            return res.status(502).json({ error: 'Gitea unavailable', details: err.message });
        }
    },

    async create(req: Request, res: Response) {
        try {
            const { name, description, isPrivate } = req.body;
            if (!name) return res.status(400).json({ error: 'name is required' });
            const repo = await giteaService.createRepo(name, description, isPrivate);
            return res.json(repo);
        } catch (err: any) {
            return res.status(500).json({ error: err.message });
        }
    },

    async get(req: Request, res: Response) {
        try {
            const { owner, name } = req.params;
            const repo = await giteaService.getRepo(owner, name);
            return res.json(repo);
        } catch (err: any) {
            return res.status(404).json({ error: 'Repository not found', details: err.message });
        }
    },

    async commit(req: Request, res: Response) {
        try {
            const { owner, name } = req.params;
            const { files, message } = req.body;
            if (!files || !message) {
                return res.status(400).json({ error: 'files and message are required' });
            }

            // Try Gitea API first for each file
            const results = [];
            for (const file of files) {
                const sha = await giteaService.getFileSha(owner, name, file.path);
                const result = await giteaService.createOrUpdateFile(
                    owner, name, file.path, file.content, message, sha || undefined
                );
                results.push(result);
            }

            return res.json({ ok: true, results });
        } catch (err: any) {
            return res.status(500).json({ error: err.message });
        }
    },

    async getCommits(req: Request, res: Response) {
        try {
            const { owner, name } = req.params;
            const commits = await giteaService.getCommits(owner, name);
            return res.json(commits);
        } catch (err: any) {
            return res.status(502).json({ error: err.message });
        }
    },

    async getFiles(req: Request, res: Response) {
        try {
            const { owner, name } = req.params;
            const tree = await giteaService.getTree(owner, name);
            return res.json(tree);
        } catch (err: any) {
            return res.status(502).json({ error: err.message });
        }
    },

    getGiteaSettings(_req: Request, res: Response) {
        return res.json(giteaService.getConfig());
    },

    updateGiteaSettings(req: Request, res: Response) {
        const { url, token, username } = req.body;
        giteaService.updateConfig({ url, token, username });
        return res.json({ ok: true, config: giteaService.getConfig() });
    },
};
