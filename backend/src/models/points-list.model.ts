import { Point } from './point.model';
import { ServerDevice } from './device.model';

export interface PointsList {
  id?: number;
  configId: string;
  name: string;
  devices: ServerDevice[];
  points: Point[];
  generatedAt: Date;
}

export interface ParsedConfig {
  id: string;
  filename: string;
  uploadedAt: Date;
  devices: ServerDevice[];
  points: Point[];
  rawXml: string;
  metadata: Record<string, string>;
}
