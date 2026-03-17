FROM nginx:1.27-alpine

COPY deploy/nginx/templates /etc/nginx/templates/managed
COPY deploy/nginx/render-nginx-config.sh /usr/local/bin/render-nginx-config.sh
COPY deploy/nginx/docker-entrypoint.d/30-render-config.sh /docker-entrypoint.d/30-render-config.sh

RUN chmod +x /usr/local/bin/render-nginx-config.sh /docker-entrypoint.d/30-render-config.sh
