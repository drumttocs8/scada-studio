/**
 * Points List Service
 * Generates structured points lists from parsed RTAC XML data.
 * TypeScript port of rtac-plg/src/generate_points_by_device.py
 */

import { Point } from '../models/point.model';
import { ServerDevice } from '../models/device.model';
import { TagMapping, DATA_TYPE_MAPPING } from './parser.service';

const CONTROL_TYPES = new Set(['operAPC', 'operSPC']);
const POINT_TYPE_ORDER: Record<string, number> = { BI: 1, AI: 2, BO: 3, AO: 4, CT: 5 };

export interface PointsListRow {
    destination: string;
    source: string;
    dataType: string;
    pointType: string;
    index: string;
    comment: string;
    mapName: string;
}

export interface PointsListByDevice {
    [deviceName: string]: {
        mapName: string;
        rows: PointsListRow[];
        duplicates: number;
    };
}

/** Extract source tag name from Tag Processor SourceExpression. */
function extractSourceTag(expr: string): string {
    if (!expr) return '';
    const parts = expr.split(/\s+/);
    return parts[0]?.replace(/[(<>=!\-+*/%]+$/, '') || '';
}

/** Generate points list grouped by server device with source/destination mapping. */
export function generatePointsByDevice(
    devices: ServerDevice[],
    points: Point[],
    tagMappings: TagMapping[],
    dataTypeMapping: Record<string, string> = DATA_TYPE_MAPPING
): PointsListByDevice {
    // Index parsed points by name
    const pointsByName = new Map<string, Point>();
    for (const p of points) {
        if (p.name) pointsByName.set(p.name, p);
    }

    const rowsByDevice: Record<string, PointsListRow[]> = {};
    const seen = new Map<string, number>(); // dedup tracking
    const duplicateCounts: Record<string, number> = {};

    for (const mapping of tagMappings) {
        const destTag = mapping.destinationTag;
        const sourceExpr = mapping.sourceExpression;
        const destDataType = mapping.dataType;
        const sourceTagName = extractSourceTag(sourceExpr);

        // Look up source tag
        const sourcePoint = sourceTagName ? pointsByName.get(sourceTagName) : undefined;
        const sourceDataType = sourcePoint?.type || '';
        const isControl = CONTROL_TYPES.has(sourceDataType);

        let devicePointName: string;
        let deviceDataType: string;
        let destination: string;
        let source: string;
        let pointInfo: Point | undefined;

        if (isControl) {
            devicePointName = sourceTagName;
            deviceDataType = sourceDataType;
            destination = destTag;
            source = sourceTagName;
            pointInfo = sourcePoint;
        } else {
            devicePointName = destTag;
            deviceDataType = destDataType;
            destination = destTag;
            source = sourceTagName;
            pointInfo = pointsByName.get(destTag);
        }

        if (!pointInfo) continue;

        const mapName = pointInfo.mapName || '';
        const index = pointInfo.address || '';
        if (!mapName) continue;

        if (!rowsByDevice[mapName]) rowsByDevice[mapName] = [];

        const pointType = dataTypeMapping[deviceDataType] || '';
        const entryKey = `${devicePointName}|${source}|${deviceDataType}|${index}`;
        let comment = pointInfo.description || '';

        if (seen.has(entryKey)) {
            duplicateCounts[mapName] = (duplicateCounts[mapName] || 0) + 1;
            comment = `[DUPLICATE] ${comment}`;
        } else {
            seen.set(entryKey, mapping.rowIndex);
        }

        rowsByDevice[mapName].push({
            destination,
            source,
            dataType: deviceDataType,
            pointType,
            index,
            comment,
            mapName,
        });
    }

    // Build result grouped by device
    const result: PointsListByDevice = {};
    for (const device of devices) {
        const mapName = device.mapName;
        const rows = rowsByDevice[mapName] || [];

        // Sort: by point type order, then by index
        rows.sort((a, b) => {
            const orderA = POINT_TYPE_ORDER[a.pointType] ?? 999;
            const orderB = POINT_TYPE_ORDER[b.pointType] ?? 999;
            if (orderA !== orderB) return orderA - orderB;
            const idxA = parseInt(a.index) || 0;
            const idxB = parseInt(b.index) || 0;
            return idxA - idxB;
        });

        result[device.deviceName] = {
            mapName,
            rows,
            duplicates: duplicateCounts[mapName] || 0,
        };
    }

    return result;
}

/** Generate a flat points list (all devices combined). */
export function generateFlatPointsList(points: Point[]): any[] {
    return points.map((p) => ({
        'Point Name': p.name || '',
        Address: p.address || '',
        Type: p.type || '',
        Units: p.units || '',
        Description: p.description || '',
        'Map Name': p.mapName || '',
        'Source File': p.sourceFile || '',
    }));
}
