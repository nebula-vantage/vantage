FROM caddy:2-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY index.html styles.css script.js config.js /srv/
COPY assets/ /srv/assets/

RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

EXPOSE 8080
