import { Router } from 'express';
import { configController } from '../controllers/config.controller';
import { queryController } from '../controllers/query.controller';
import { repositoryController } from '../controllers/repository.controller';
import { diffController } from '../controllers/diff.controller';
import { authController } from '../controllers/auth.controller';
import { upload } from '../middleware/validation';

export const router = Router();

// Health
router.get('/status', (_req, res) => res.json({ ok: true }));

// Auth
router.post('/auth/login', authController.login);
router.get('/auth/verify', authController.verify);

// Config / File operations
router.post('/configs/upload', upload.single('file'), configController.upload);
router.get('/configs', configController.list);
router.get('/configs/:id', configController.get);
router.delete('/configs/:id', configController.remove);
router.get('/configs/:id/points', configController.getPoints);
router.get('/configs/:id/devices', configController.getDevices);
router.get('/configs/:id/xml', configController.getXml);

// Points list generation
router.post('/configs/:id/generate-points', configController.generatePointsList);

// Query / RAG search
router.post('/query/search', queryController.search);
router.post('/query/cim-topology', queryController.cimTopology);

// Repository / Gitea
router.get('/repos', repositoryController.list);
router.post('/repos', repositoryController.create);
router.get('/repos/:owner/:name', repositoryController.get);
router.post('/repos/:owner/:name/commit', repositoryController.commit);
router.get('/repos/:owner/:name/commits', repositoryController.getCommits);
router.get('/repos/:owner/:name/files', repositoryController.getFiles);

// Diff
router.get('/diff/:owner/:name/:sha', diffController.getCommitDiff);
router.post('/diff/compare', diffController.compare);

// Gitea connection settings
router.get('/settings/gitea', repositoryController.getGiteaSettings);
router.post('/settings/gitea', repositoryController.updateGiteaSettings);
