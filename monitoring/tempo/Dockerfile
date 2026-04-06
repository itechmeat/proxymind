FROM busybox:1.37.0-musl AS busybox

FROM grafana/tempo:2.10.3

COPY --from=busybox /bin/wget /bin/wget
