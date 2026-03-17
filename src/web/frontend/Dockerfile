FROM node:20-alpine AS base

WORKDIR /app/src/web/frontend
ENV NEXT_TELEMETRY_DISABLED=1

FROM base AS deps

COPY src/web/frontend/package*.json ./
RUN npm ci

FROM deps AS build

ARG NEXT_PUBLIC_API_BASE=/api/v1
ENV NODE_ENV=production
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

COPY src/web/frontend .
COPY assets /app/assets
RUN npm run build

FROM base AS prod-deps

COPY src/web/frontend/package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

FROM base AS prod

ENV NODE_ENV=production

COPY --from=prod-deps /app/src/web/frontend/node_modules ./node_modules
COPY --from=build /app/src/web/frontend/package*.json ./
COPY --from=build /app/src/web/frontend/next.config.mjs ./next.config.mjs
COPY --from=build /app/src/web/frontend/.next ./.next

CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]

FROM deps AS dev

COPY src/web/frontend .
COPY assets /app/assets

CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3000"]
