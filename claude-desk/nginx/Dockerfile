# The UI is baked in rather than bind-mounted: directories under
# /volume2/docker carry the DSM share ACL, which the nginx worker (uid 101)
# cannot traverse — a `./ui:/usr/share/nginx/html` bind serves 403 for every
# file. Single files (nginx.conf, .htpasswd) are fine because the master
# process reads them as root, so those stay as binds in docker-compose.yml.
FROM nginx:alpine
COPY ui/ /usr/share/nginx/html/
# The tar|ssh upload lands files as 0700; COPY keeps that, the worker runs
# as uid 101 → 403 on everything. Normalise here instead of on the NAS.
RUN chmod -R a+rX /usr/share/nginx/html
