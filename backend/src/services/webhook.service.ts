/**
 * Webhook Service
 * Handles incoming webhooks from Gitea for auto-sync of config changes.
 */

import { Request } from 'express';

export interface WebhookPayload {
    ref: string;
    repository: {
        full_name: string;
        clone_url: string;
    };
    commits: Array<{
        id: string;
        message: string;
        added: string[];
        modified: string[];
        removed: string[];
    }>;
}

export const webhookService = {
    parseGiteaPush(req: Request): WebhookPayload | null {
        const event = req.headers['x-gitea-event'];
        if (event !== 'push') return null;
        return req.body as WebhookPayload;
    },

    getChangedXmlFiles(payload: WebhookPayload): string[] {
        const xmlFiles = new Set<string>();
        for (const commit of payload.commits) {
            for (const f of [...commit.added, ...commit.modified]) {
                if (f.toLowerCase().endsWith('.xml')) {
                    xmlFiles.add(f);
                }
            }
        }
        return Array.from(xmlFiles);
    },
};
