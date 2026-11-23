# A USER line inside a heredoc is file content, not an instruction: this image runs as root.
# seeded below: RT-DOCKER-ROOT
FROM python:3.12-slim
RUN <<EOF
set -e
cat > /etc/motd <<'NOTE'
USER guide: log in as app
NOTE
EOF
CMD ["python", "-c", "print('ok')"]
