import { Request, Response } from 'express';
import { giteaService } from '../services/gitea.service';

export const diffController = {
  async getCommitDiff(req: Request, res: Response) {
    try {
      const { owner, name, sha } = req.params;
      const diff = await giteaService.getDiff(owner, name, sha);
      return res.json(diff);
    } catch (err: any) {
      return res.status(502).json({ error: err.message });
    }
  },

  async compare(req: Request, res: Response) {
    try {
      const { xml1, xml2, label1, label2 } = req.body;
      if (!xml1 || !xml2) {
        return res.status(400).json({ error: 'xml1 and xml2 are required' });
      }

      // Simple line-by-line diff
      const lines1 = xml1.split('\n');
      const lines2 = xml2.split('\n');
      const changes: Array<{ type: 'added' | 'removed' | 'unchanged'; line: string; lineNumber: number }> = [];

      const maxLen = Math.max(lines1.length, lines2.length);
      for (let i = 0; i < maxLen; i++) {
        const l1 = lines1[i] ?? '';
        const l2 = lines2[i] ?? '';
        if (l1 === l2) {
          changes.push({ type: 'unchanged', line: l1, lineNumber: i + 1 });
        } else {
          if (l1) changes.push({ type: 'removed', line: l1, lineNumber: i + 1 });
          if (l2) changes.push({ type: 'added', line: l2, lineNumber: i + 1 });
        }
      }

      return res.json({
        label1: label1 || 'Original',
        label2: label2 || 'Modified',
        totalChanges: changes.filter((c) => c.type !== 'unchanged').length,
        changes,
      });
    } catch (err: any) {
      return res.status(500).json({ error: err.message });
    }
  },
};
