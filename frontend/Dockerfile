# Build stage
FROM node:20-alpine AS build

WORKDIR /app

# Copy the manifest and committed lockfile before source code for a stable cache layer.
COPY package.json package-lock.json ./

# Install exactly the dependency graph recorded in package-lock.json.
RUN npm ci

# Copy source files
COPY . .

# Build the app
RUN npm run build

# Production stage with nginx
FROM nginx:alpine

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
