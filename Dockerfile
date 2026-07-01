# syntax=docker/dockerfile:1
# Debian/glibc Node image: a clean pnpm install here reliably pulls Tailwind v4's
# platform-native binary (@tailwindcss/oxide-linux-x64-gnu), which the Nixpacks
# build failed to install. Deterministic and mirrors the engine's Dockerfile.
FROM node:22-slim

WORKDIR /app
RUN corepack enable

# Install all deps (dev + optional platform binaries) — needed to build.
COPY package.json pnpm-lock.yaml .npmrc ./
RUN pnpm install --frozen-lockfile

# Build the Next.js app.
COPY . .
RUN pnpm build

ENV NODE_ENV=production
EXPOSE 3000
# next start binds 0.0.0.0 and honours $PORT (Railway injects it) with no flags.
CMD ["pnpm", "start"]
