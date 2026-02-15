# --- Build frontend ---
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend

ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --silent 2>/dev/null || npm install --silent
COPY frontend/ ./
RUN npm run build

# --- Build backend ---
FROM node:20-alpine AS backend-build
WORKDIR /app/backend
COPY backend/package.json backend/package-lock.json* ./
RUN npm ci --silent 2>/dev/null || npm install --silent
COPY backend/ ./
RUN npm run build

# --- Production ---
FROM node:20-alpine
WORKDIR /app

# Copy backend build + deps
COPY --from=backend-build /app/backend/dist ./dist
COPY --from=backend-build /app/backend/node_modules ./node_modules
COPY --from=backend-build /app/backend/package.json ./package.json

# Copy frontend build into backend's public dir
COPY --from=frontend-build /app/frontend/dist ./public

# Environment defaults
ENV NODE_ENV=production

# Railway injects PORT dynamically; do not hardcode EXPOSE
CMD ["node", "dist/app.js"]
