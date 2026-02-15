export interface Device {
    id?: number;
    name: string;
    filePath: string;
    repository: string;
    protocol?: string;
    firmwareVersion?: string;
    deviceType?: string;
    lastModified?: Date;
    gitCommitHash?: string;
    createdAt?: Date;
}

export interface ServerDevice {
    deviceName: string;
    mapName: string;
    sourceFile: string;
}
