FROM node:18 AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN VITE_API_BASE_URL= npm run build

FROM python:3.11-slim
WORKDIR /app

# Install supervisor and nginx
RUN apt-get update && apt-get install -y supervisor nginx && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy backend code
COPY backend/ /app/backend/

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Configure Nginx
RUN echo 'server { \
    listen 8080; \
    server_name _; \
    \
    location /api/ { \
        proxy_pass http://127.0.0.1:8000; \
        proxy_set_header Host $host; \
        proxy_set_header X-Real-IP $remote_addr; \
    } \
    \
    location / { \
        root /app/frontend/dist; \
        try_files $uri $uri/ /index.html; \
    } \
}' > /etc/nginx/sites-available/default

# Configure Supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# We will use SQLite for a seamless zero-config deployment if DATABASE_URL is not provided
# Make sure the SQLite DB is writable by the app
RUN chmod 777 /app/backend
RUN touch /app/backend/db.sqlite3 && chmod 666 /app/backend/db.sqlite3

EXPOSE 8080

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
