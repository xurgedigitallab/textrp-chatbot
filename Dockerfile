FROM evernode/sashimono:hp.latest-ubt.20.04-njs.20

ENV NODE_ENV=production \
    HP_STATE_DIR=/hp/state

WORKDIR /app

COPY package.json package-lock.json tsconfig.json ./
RUN npm ci

COPY src ./src
RUN npm run build

RUN mkdir -p /hp/state

EXPOSE 9009

CMD ["npm", "start"]
