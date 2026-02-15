import { Request, Response } from 'express';
import { generateToken } from '../middleware/auth';

export const authController = {
    login(req: Request, res: Response) {
        // Simple auth — in production use proper user management
        const { username, password } = req.body;
        const adminUser = process.env.ADMIN_USER || 'admin';
        const adminPass = process.env.ADMIN_PASSWORD || 'scada-studio';

        if (username === adminUser && password === adminPass) {
            const token = generateToken(username);
            return res.json({ token, username });
        }
        return res.status(401).json({ error: 'Invalid credentials' });
    },

    verify(req: Request, res: Response) {
        const token = req.headers.authorization?.replace('Bearer ', '');
        if (!token) return res.status(401).json({ error: 'No token' });
        try {
            const jwt = require('jsonwebtoken');
            const decoded = jwt.verify(token, process.env.JWT_SECRET || 'scada-studio-dev-secret');
            return res.json({ valid: true, userId: decoded.userId });
        } catch {
            return res.status(401).json({ error: 'Invalid token' });
        }
    },
};
