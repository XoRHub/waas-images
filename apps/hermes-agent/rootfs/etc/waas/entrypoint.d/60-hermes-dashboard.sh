# Supervise the Hermes web dashboard (sourced by waas-entrypoint, which
# provides RUNDIR/log and strict mode — the 50-sshd.sh precedent).
# Loopback only (upstream default bind is 127.0.0.1): reachable solely
# from inside the session, i.e. through the password-gated VNC display.
# The web UI is prebuilt at image build time — the code tree under
# /usr/local is root-owned and read-only at runtime, a lazy first-run
# build could never work.
if [[ "${WAAS_HERMES_DASHBOARD:-1}" != "0" ]]; then
    cat > "${RUNDIR}/supervisor.d/60-hermes-dashboard.conf" <<EOF
[program:hermes-dashboard]
command=/usr/local/bin/hermes dashboard
priority=40
autorestart=true
environment=HOME="${HOME}"
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
redirect_stderr=true
EOF
    log "hermes dashboard enabled (127.0.0.1:9119; WAAS_HERMES_DASHBOARD=0 disables)"
else
    log "hermes dashboard disabled (WAAS_HERMES_DASHBOARD=0)"
fi
