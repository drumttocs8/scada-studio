import { Request, Response } from 'express';
import fs from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { parseXmlContent, ParseResult } from '../services/parser.service';
import { generatePointsByDevice, generateFlatPointsList } from '../services/points-list.service';
import { ParsedConfig } from '../models/points-list.model';

// In-memory store for parsed configs (in production, use DB)
const configs = new Map<string, ParsedConfig>();

export const configController = {
  async upload(req: Request, res: Response) {
    try {
      if (!req.file) {
        return res.status(400).json({ error: 'No file uploaded' });
      }

      const filePath = req.file.path;
      const filename = req.file.originalname;
      const content = fs.readFileSync(filePath, 'utf-8');
      const id = uuidv4();

      let result: ParseResult;
      try {
        result = parseXmlContent(content, filename);
      } catch (parseErr: any) {
        return res.status(400).json({
          error: 'Failed to parse XML',
          details: parseErr.message,
        });
      }

      const config: ParsedConfig = {
        id,
        filename,
        uploadedAt: new Date(),
        devices: result.devices,
        points: result.points,
        rawXml: content,
        metadata: {
          totalDevices: String(result.devices.length),
          totalPoints: String(result.points.length),
          totalTagMappings: String(result.tagMappings.length),
        },
      };

      configs.set(id, config);

      // Clean up temp file
      fs.unlinkSync(filePath);

      return res.json({
        id,
        filename,
        devices: result.devices.length,
        points: result.points.length,
        tagMappings: result.tagMappings.length,
      });
    } catch (err: any) {
      return res.status(500).json({ error: err.message });
    }
  },

  list(_req: Request, res: Response) {
    const list = Array.from(configs.values()).map((c) => ({
      id: c.id,
      filename: c.filename,
      uploadedAt: c.uploadedAt,
      devices: c.devices.length,
      points: c.points.length,
    }));
    return res.json(list);
  },

  get(req: Request, res: Response) {
    const config = configs.get(req.params.id);
    if (!config) return res.status(404).json({ error: 'Config not found' });
    return res.json({
      id: config.id,
      filename: config.filename,
      uploadedAt: config.uploadedAt,
      devices: config.devices,
      points: config.points,
      metadata: config.metadata,
    });
  },

  remove(req: Request, res: Response) {
    const deleted = configs.delete(req.params.id);
    if (!deleted) return res.status(404).json({ error: 'Config not found' });
    return res.json({ ok: true });
  },

  getPoints(req: Request, res: Response) {
    const config = configs.get(req.params.id);
    if (!config) return res.status(404).json({ error: 'Config not found' });
    return res.json(config.points);
  },

  getDevices(req: Request, res: Response) {
    const config = configs.get(req.params.id);
    if (!config) return res.status(404).json({ error: 'Config not found' });
    return res.json(config.devices);
  },

  getXml(req: Request, res: Response) {
    const config = configs.get(req.params.id);
    if (!config) return res.status(404).json({ error: 'Config not found' });
    res.setHeader('Content-Type', 'application/xml');
    return res.send(config.rawXml);
  },

  generatePointsList(req: Request, res: Response) {
    const config = configs.get(req.params.id);
    if (!config) return res.status(404).json({ error: 'Config not found' });

    const flat = generateFlatPointsList(config.points);
    return res.json({
      configId: config.id,
      filename: config.filename,
      totalPoints: flat.length,
      points: flat,
    });
  },
};
