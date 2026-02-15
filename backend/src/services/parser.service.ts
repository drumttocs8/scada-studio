/**
 * RTAC XML Parser Service
 * TypeScript port of rtac-plg/src/parse_rtac_xml.py
 * Parses RTAC XML exports extracting point records, devices, and tag mappings.
 */

import { XMLParser } from 'fast-xml-parser';
import fs from 'fs';
import path from 'path';
import { Point } from '../models/point.model';
import { ServerDevice } from '../models/device.model';

const POINT_TAGS = new Set([
  'point', 'Point', 'Tag', 'tag', 'DataPoint', 'datapoint',
  'DevicePoint', 'devicepoint',
]);

const parser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: '@_',
  textNodeName: '#text',
  isArray: (name) => ['Row', 'Setting', 'SettingPage', 'TagList', 'Device'].includes(name),
});

export interface ParseResult {
  devices: ServerDevice[];
  points: Point[];
  tagMappings: TagMapping[];
}

export interface TagMapping {
  destinationTag: string;
  sourceExpression: string;
  dataType: string;
  rowIndex: number;
  comment: string;
  settings: Record<string, string>;
}

/** Extract a setting value from a row's settings array. */
function getSettingValue(settings: any[], columnName: string): string {
  if (!Array.isArray(settings)) return '';
  for (const setting of settings) {
    const col = setting?.Column;
    const val = setting?.Value;
    if (col === columnName) return val || '';
  }
  return '';
}

/** Build a key→value map from a row's settings array. */
function settingsToMap(settings: any[]): Record<string, string> {
  const map: Record<string, string> = {};
  if (!Array.isArray(settings)) return map;
  for (const s of settings) {
    if (s?.Column && s?.Value !== undefined) {
      map[s.Column] = s.Value?.toString() || '';
    }
  }
  return map;
}

/** Parse RTAC TagList format (DNP/Modbus device exports). */
function parseTagList(settingPage: any, filename: string, mapName = ''): Point[] {
  const points: Point[] = [];
  const rows = settingPage?.Row || [];
  for (const row of rows) {
    const settings = row?.Setting || [];
    const map = settingsToMap(settings);

    if (map['Enable']?.toLowerCase() !== 'true') continue;

    const point: Point = {
      name: map['Tag Name'] || '',
      address: map['Point Number'] || '',
      type: map['Tag Type'] || '',
      description: map['Comment'] || '',
      mapName: mapName || undefined,
      sourceFile: filename,
    };

    if (point.name) {
      points.push(point);
    }
  }
  return points;
}

/** Parse a device XML structure. */
function parseDevice(device: any, filename: string): { devices: ServerDevice[]; points: Point[] } {
  const serverDevices: ServerDevice[] = [];
  const points: Point[] = [];

  const nameElem = device?.Name;
  const deviceName = typeof nameElem === 'string' ? nameElem : filename;

  // Check for DNPServer connection with Map Name
  const connection = device?.Connection;
  if (connection) {
    const protocol = connection?.Protocol;
    if (protocol === 'DNPServer') {
      let mapName = '';
      // Search SettingPages for Map Name
      const settingPages = connection?.SettingPages?.SettingPage ||
        connection?.SettingPage || [];
      const pages = Array.isArray(settingPages) ? settingPages : [settingPages];

      for (const page of pages) {
        const rows = page?.Row || [];
        for (const row of rows) {
          const settings = row?.Setting || [];
          if (settings.length >= 2) {
            const first = settings[0];
            if (first?.Column === 'Setting' && first?.Value === 'Map Name') {
              const second = settings[1];
              if (second?.Column === 'Value' && second?.Value) {
                mapName = second.Value;
                break;
              }
            }
          }
        }
        if (mapName) break;
      }

      if (mapName) {
        serverDevices.push({ deviceName, mapName, sourceFile: filename });
      }

      // Parse TagLists within device
      const tagLists = device?.TagList || [];
      const lists = Array.isArray(tagLists) ? tagLists : [tagLists];
      for (const tl of lists) {
        const pages2 = tl?.SettingPage || [];
        const pArr = Array.isArray(pages2) ? pages2 : [pages2];
        for (const p of pArr) {
          points.push(...parseTagList(p, filename, mapName));
        }
      }
    }
  }

  return { devices: serverDevices, points };
}

/** Parse Tag Processor XML and extract ALL tag mappings with data types. */
function parseTagProcessor(xmlContent: string, filename: string): TagMapping[] {
  const mappings: TagMapping[] = [];
  try {
    const doc = parser.parse(xmlContent);
    let rowIndex = 0;

    // Navigate to SettingPage rows
    const findRows = (obj: any): any[] => {
      if (!obj || typeof obj !== 'object') return [];
      if (obj.Row) return Array.isArray(obj.Row) ? obj.Row : [obj.Row];
      if (obj.SettingPage) {
        const pages = Array.isArray(obj.SettingPage) ? obj.SettingPage : [obj.SettingPage];
        return pages.flatMap((p: any) => findRows(p));
      }
      return Object.values(obj).flatMap((v: any) => findRows(v));
    };

    const rows = findRows(doc);
    for (const row of rows) {
      rowIndex++;
      const settings = row?.Setting || [];
      const map = settingsToMap(settings);
      const destTag = map['DestinationTagName'] || '';
      if (destTag) {
        mappings.push({
          destinationTag: destTag,
          sourceExpression: map['SourceExpression'] || '',
          dataType: map['DTDataType'] || '',
          rowIndex,
          comment: map['Comment'] || map['Description'] || map['LoggingOnMessage'] || '',
          settings: map,
        });
      }
    }
  } catch (err) {
    console.warn(`Warning: failed to parse tag processor ${filename}:`, err);
  }
  return mappings;
}

/** Parse a single XML file and return devices + points. */
export function parseXmlContent(xmlContent: string, filename: string): ParseResult {
  const doc = parser.parse(xmlContent);
  const allDevices: ServerDevice[] = [];
  const allPoints: Point[] = [];
  const tagMappings: TagMapping[] = [];

  // Try Device structure
  const findDevices = (obj: any): any[] => {
    if (!obj || typeof obj !== 'object') return [];
    if (obj.Device) return Array.isArray(obj.Device) ? obj.Device : [obj.Device];
    return Object.values(obj).flatMap((v: any) => findDevices(v));
  };

  const devices = findDevices(doc);
  if (devices.length > 0) {
    for (const dev of devices) {
      const result = parseDevice(dev, filename);
      allDevices.push(...result.devices);
      allPoints.push(...result.points);
    }
    return { devices: allDevices, points: allPoints, tagMappings };
  }

  // Try TagList structure
  const findTagLists = (obj: any): any[] => {
    if (!obj || typeof obj !== 'object') return [];
    if (obj.TagList) return Array.isArray(obj.TagList) ? obj.TagList : [obj.TagList];
    return Object.values(obj).flatMap((v: any) => findTagLists(v));
  };

  const tagLists = findTagLists(doc);
  if (tagLists.length > 0) {
    for (const tl of tagLists) {
      const pages = tl?.SettingPage || [];
      const pArr = Array.isArray(pages) ? pages : [pages];
      for (const p of pArr) {
        allPoints.push(...parseTagList(p, filename));
      }
    }
    return { devices: allDevices, points: allPoints, tagMappings };
  }

  // Try Tag Processor structure (check for DestinationTagName in settings)
  const xmlLower = xmlContent.toLowerCase();
  if (xmlLower.includes('destinationtagname') || xmlLower.includes('sourceexpression')) {
    const tm = parseTagProcessor(xmlContent, filename);
    tagMappings.push(...tm);
    return { devices: allDevices, points: allPoints, tagMappings };
  }

  // Fallback: generic point extraction
  const findPoints = (obj: any, prefix = ''): Point[] => {
    if (!obj || typeof obj !== 'object') return [];
    const pts: Point[] = [];
    for (const [key, value] of Object.entries(obj)) {
      if (POINT_TAGS.has(key)) {
        const items = Array.isArray(value) ? value : [value];
        for (const item of items) {
          if (typeof item === 'object') {
            pts.push({
              name: item.name || item.Name || item.id || item.Id || item['@_name'] || item['@_id'] || '',
              address: item.address || item.Address || item.addr || '',
              type: item.type || item.Type || item.pointtype || '',
              units: item.units || item.Units || item.unit || '',
              description: item.description || item.Description || item.desc || '',
              sourceFile: filename,
            });
          }
        }
      } else if (typeof value === 'object') {
        pts.push(...findPoints(value, `${prefix}${key}.`));
      }
    }
    return pts;
  };

  allPoints.push(...findPoints(doc));
  return { devices: allDevices, points: allPoints, tagMappings };
}

/** Parse all XML files in a directory. */
export function parseDirectory(dirPath: string): ParseResult {
  const allDevices: ServerDevice[] = [];
  const allPoints: Point[] = [];
  const allTagMappings: TagMapping[] = [];
  const mapNames = new Map<string, string>();

  // First pass: extract server devices and build map
  const xmlFiles = findXmlFiles(dirPath);
  for (const filePath of xmlFiles) {
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      const result = parseXmlContent(content, path.basename(filePath));
      if (result.devices.length > 0) {
        allDevices.push(...result.devices);
        for (const dev of result.devices) {
          mapNames.set(dev.mapName, dev.mapName);
        }
      }
    } catch (err) {
      console.warn(`Warning: failed to parse ${filePath}:`, err);
    }
  }

  // Second pass: parse all points and assign map names
  for (const filePath of xmlFiles) {
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      const result = parseXmlContent(content, path.basename(filePath));
      if (result.devices.length === 0) {
        // TagList file — try to infer map name
        for (const point of result.points) {
          const pointName = point.name || '';
          for (const mn of mapNames.keys()) {
            if (pointName.startsWith(mn + '.')) {
              point.mapName = mn;
              break;
            }
          }
        }
        allPoints.push(...result.points);
      }
      allTagMappings.push(...result.tagMappings);
    } catch (err) {
      console.warn(`Warning: failed to parse ${filePath}:`, err);
    }
  }

  return { devices: allDevices, points: allPoints, tagMappings: allTagMappings };
}

function findXmlFiles(dirPath: string): string[] {
  const files: string[] = [];
  if (!fs.existsSync(dirPath)) return files;
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...findXmlFiles(fullPath));
    } else if (entry.name.toLowerCase().endsWith('.xml')) {
      files.push(fullPath);
    }
  }
  return files;
}

/** Data type to point type mapping (from RTAC PLG schema). */
export const DATA_TYPE_MAPPING: Record<string, string> = {
  MV: 'AI', CMV: 'AI', INT: 'AI',
  SPS: 'BI', BOOL: 'BI',
  BCR: 'CT',
  operAPC: 'AO', operSPC: 'BO',
};

const CONTROL_TYPES = new Set(['operAPC', 'operSPC']);
