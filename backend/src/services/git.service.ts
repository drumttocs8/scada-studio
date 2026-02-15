/**
 * Local Git Service
 * Handles local git operations using simple-git.
 */

import simpleGit, { SimpleGit } from 'simple-git';
import path from 'path';
import fs from 'fs';

const REPOS_DIR = process.env.REPOS_DIR || path.join(process.cwd(), 'repos');

// Ensure repos directory exists
fs.mkdirSync(REPOS_DIR, { recursive: true });

function getRepoPath(owner: string, name: string): string {
    return path.join(REPOS_DIR, owner, name);
}

function getGit(owner: string, name: string): SimpleGit {
    return simpleGit(getRepoPath(owner, name));
}

export const gitService = {
    async clone(cloneUrl: string, owner: string, name: string): Promise<void> {
        const repoPath = getRepoPath(owner, name);
        if (fs.existsSync(repoPath)) {
            // Already cloned, just pull
            await getGit(owner, name).pull();
            return;
        }
        fs.mkdirSync(path.dirname(repoPath), { recursive: true });
        await simpleGit().clone(cloneUrl, repoPath);
    },

    async commitAndPush(
        owner: string,
        name: string,
        files: { path: string; content: string }[],
        message: string
    ): Promise<string> {
        const repoPath = getRepoPath(owner, name);
        const git = getGit(owner, name);

        // Write files
        for (const file of files) {
            const filePath = path.join(repoPath, file.path);
            fs.mkdirSync(path.dirname(filePath), { recursive: true });
            fs.writeFileSync(filePath, file.content, 'utf-8');
        }

        // Stage, commit, push
        await git.add('.');
        const result = await git.commit(message);
        try {
            await git.push();
        } catch (err) {
            console.warn('Push failed (may be local-only repo):', err);
        }
        return result.commit || 'committed';
    },

    async getLog(owner: string, name: string, maxCount = 20) {
        const git = getGit(owner, name);
        const log = await git.log({ maxCount });
        return log.all;
    },

    async getDiff(owner: string, name: string, sha: string) {
        const git = getGit(owner, name);
        return git.diff([`${sha}~1`, sha]);
    },

    async listFiles(owner: string, name: string): Promise<string[]> {
        const git = getGit(owner, name);
        const result = await git.raw(['ls-tree', '-r', '--name-only', 'HEAD']);
        return result.trim().split('\n').filter(Boolean);
    },

    repoExists(owner: string, name: string): boolean {
        return fs.existsSync(getRepoPath(owner, name));
    },
};
