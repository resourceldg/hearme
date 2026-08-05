FROM node:22-alpine AS builder
WORKDIR /app

# Metadatos primero: esta capa se cachea mientras no cambien las dependencias.
COPY package*.json ./
RUN npm ci

# El resto del código. `.dockerignore` excluye node_modules y build: sin él,
# esta línea sobreescribía los módulos recién instalados con los del anfitrión,
# compilados para otra libc.
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=builder /app/build ./build
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
USER node
EXPOSE 3000
CMD ["node", "build"]
