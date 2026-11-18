# syntax=docker/dockerfile:1.7
FROM node:22.12.0-bookworm-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
# --ignore-scripts: no install-time code from dependencies.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27.3-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
