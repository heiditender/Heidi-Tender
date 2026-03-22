FROM node:20-alpine AS base

WORKDIR /app/src/web/frontend
ENV NEXT_TELEMETRY_DISABLED=1 \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false
RUN mkdir -p /app/src/web/frontend && chown -R node:node /app

FROM base AS deps

COPY src/web/frontend/package*.json ./
RUN npm ci --no-audit --no-fund

FROM base AS build

COPY src/web/frontend/package*.json ./
RUN npm ci --no-audit --no-fund

ARG NEXT_PUBLIC_API_BASE=/api/v1
ENV NODE_ENV=production
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

COPY src/web/frontend .
COPY assets /app/assets
RUN npm run build

FROM base AS prod-deps

COPY src/web/frontend/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force

FROM base AS prod

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

COPY --from=prod-deps --chown=node:node /app/src/web/frontend/node_modules ./node_modules
COPY --from=build --chown=node:node /app/src/web/frontend/package*.json ./
COPY --from=build --chown=node:node /app/src/web/frontend/next.config.mjs ./next.config.mjs
COPY --from=build --chown=node:node /app/src/web/frontend/.next ./.next

USER node

CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]

FROM deps AS dev

COPY src/web/frontend .
COPY assets /app/assets

CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3000"]
