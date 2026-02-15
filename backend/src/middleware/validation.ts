import multer from 'multer';
import path from 'path';
import os from 'os';

const uploadDir = process.env.UPLOAD_DIR || path.join(os.tmpdir(), 'scada-studio-uploads');

const storage = multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, uploadDir),
    filename: (_req, file, cb) => {
        const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1e9);
        cb(null, uniqueSuffix + '-' + file.originalname);
    },
});

const fileFilter = (_req: any, file: Express.Multer.File, cb: multer.FileFilterCallback) => {
    const allowedExts = ['.xml', '.exp', '.json'];
    const ext = path.extname(file.originalname).toLowerCase();
    if (allowedExts.includes(ext)) {
        cb(null, true);
    } else {
        cb(new Error(`File type ${ext} not allowed. Allowed: ${allowedExts.join(', ')}`));
    }
};

export const upload = multer({
    storage,
    fileFilter,
    limits: { fileSize: 50 * 1024 * 1024 }, // 50MB
});

// Ensure upload directory exists
import fs from 'fs';
fs.mkdirSync(uploadDir, { recursive: true });
