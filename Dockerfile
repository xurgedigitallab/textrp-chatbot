FROM node:20-bullseye-slim AS build
WORKDIR /app

COPY package.json package-lock.json tsconfig.json ./
RUN npm ci --omit=optional

COPY src ./src
RUN npm run build
RUN npm prune --omit=dev --omit=optional

FROM evernode/sashimono:hp.latest-ubt.20.04-njs.20
WORKDIR /app
ENV NODE_ENV=production

COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist

EXPOSE 9009
ENTRYPOINT ["node", "dist/src/index.js"]