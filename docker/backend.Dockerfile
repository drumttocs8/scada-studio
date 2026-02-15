# Backend Dockerfile
FROM node:20-alpine
WORKDIR /app
COPY ../backend/package.json ../backend/package-lock.json ./
RUN npm install
COPY ../backend ./
RUN npm run build
EXPOSE 4000
CMD ["npm", "start"]
