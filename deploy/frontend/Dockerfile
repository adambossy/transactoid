# deploy/frontend/Dockerfile — Vite build -> nginx static serve.
#
# Build context is the REPO ROOT (consistent with the other deployables);
# paths below are relative to it. Deploy:
#
#   fly deploy --config deploy/frontend/fly.toml \
#              --dockerfile deploy/frontend/Dockerfile
#
# Single-origin model: the browser hits this app and /api/* is proxied to the
# backend (BACKEND_ORIGIN), mirroring the Vite dev proxy so the app keeps its
# one-origin assumption in production.

# =============================================================================
# Stage 1: build the static bundle
# =============================================================================
FROM node:22-alpine AS builder

WORKDIR /app

# Manifest + the vendored agent-ui tarball first (npm ci needs the file: dep
# present to resolve), for layer caching.
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/vendor ./vendor
RUN npm ci

# App source.
COPY frontend/ ./

# Clerk publishable key: a PUBLIC key that Vite inlines into the bundle at
# build time (import.meta.env.VITE_CLERK_PUBLISHABLE_KEY). With no key the app
# builds in dev/no-Clerk mode and sends no bearer token, which a Clerk-enforcing
# backend rejects — so prod builds MUST pass it:
#   fly deploy --build-arg VITE_CLERK_PUBLISHABLE_KEY=pk_...
ARG VITE_CLERK_PUBLISHABLE_KEY
ENV VITE_CLERK_PUBLISHABLE_KEY=$VITE_CLERK_PUBLISHABLE_KEY

# AGENT_UI_USE_VENDOR=1: consume the vendored @adambossy/agent-ui tarball
# under node_modules instead of the ~/code/agent-ui source alias, which does
# not exist in a container. (resolve.dedupe still applies — do not remove it.)
ENV AGENT_UI_USE_VENDOR=1
RUN npm run build

# =============================================================================
# Stage 2: static serve + /api proxy
# =============================================================================
FROM nginx:1.27-alpine AS production

COPY --from=builder /app/dist /usr/share/nginx/html
COPY deploy/frontend/nginx.conf.template /etc/nginx/templates/default.conf.template

# BACKEND_ORIGIN is substituted into the nginx template at container start
# (nginx:alpine runs envsubst over /etc/nginx/templates/*.template). Default
# points at the backend Fly app's internal name; override via fly [env].
ENV BACKEND_ORIGIN="https://penny.fly.dev"
EXPOSE 8080

# nginx:alpine's entrypoint handles envsubst + launch.
CMD ["nginx", "-g", "daemon off;"]
