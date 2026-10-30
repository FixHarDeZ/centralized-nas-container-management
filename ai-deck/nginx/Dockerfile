# The UI is baked in rather than bind-mounted: directories under
# /volume2/docker carry the DSM share ACL, which the nginx worker (uid 101)
# cannot traverse — a `./ui:/usr/share/nginx/html` bind serves 403 for every
# file. Single files (nginx.conf, .htpasswd) are fine because the master
# process reads them as root, so those stay as binds in docker-compose.yml.
# Pinned by digest; `make desk-latest` bumps it with the desk pins.
FROM nginx:alpine@sha256:785835ea65db4bba6f021acc0f3be91b0fef76a53fe41f8588c6698d2aed0606
COPY ui/ /usr/share/nginx/html/
# The tar|ssh upload lands files as 0700; COPY keeps that, the worker runs
# as uid 101 → 403 on everything. Normalise here instead of on the NAS.
RUN chmod -R a+rX /usr/share/nginx/html
