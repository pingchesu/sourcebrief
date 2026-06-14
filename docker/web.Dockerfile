FROM node:24-alpine
WORKDIR /app/apps/web
COPY apps/web/package*.json ./
RUN npm install
COPY apps/web ./
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:18000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build
CMD ["npm", "run", "start"]
