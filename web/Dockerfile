# syntax=docker/dockerfile:1.7
# Web image: the Next.js backend-for-frontend in standalone mode. Non-root, arbitrary UID,
# read-only root filesystem; /tmp and .next/cache must be writable (emptyDir mounts).
ARG NODE_IMAGE=registry.access.redhat.com/ubi9/nodejs-22:latest

FROM ${NODE_IMAGE} AS build
USER 0
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
USER 0
WORKDIR /app
COPY --from=build /build/.next/standalone ./
COPY --from=build /build/.next/static ./.next/static
COPY --from=build /build/public ./public
RUN chgrp -R 0 /app && chmod -R g=u,o-w /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000 HOME=/tmp
# the UBI base entrypoint re-sources its own PATH (system Python/Node first); run commands directly
ENTRYPOINT []
USER 1001
EXPOSE 3000
CMD ["node", "server.js"]
