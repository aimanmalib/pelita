# Static site image: nginx serving web/ at /, brand/ at /brand/, config/chains.json at /config/chains.json.
# state/public/ is NOT in the image: deploy.sh mounts it read-only at /data (the indexer rewrites it every 2 minutes).
# Built by deploy/deploy.sh from a clean `git archive` after deploy/stamp.py has versioned the assets and
# rendered deploy/nginx.conf + nginx.headers into deploy/rendered/.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ENV NGINX_ENTRYPOINT_QUIET_LOGS=1
RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/rendered/ /etc/nginx/conf.d/
COPY web/ /usr/share/nginx/html/
COPY brand/ /usr/share/nginx/html/brand/
COPY config/chains.json /usr/share/nginx/html/config/chains.json
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
