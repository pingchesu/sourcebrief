FROM node:24-alpine
WORKDIR /app/apps/web
COPY apps/web/package*.json ./
RUN npm install
COPY apps/web ./
RUN npm run build
CMD ["npm", "run", "start"]
