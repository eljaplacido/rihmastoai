FROM python:3.12-slim
RUN useradd --create-home app
WORKDIR /srv
COPY app ./app
COPY tools ./tools
RUN <<EOF
cat > /srv/report.sql <<'SQL'
SELECT owner, COUNT(*)
FROM loans GROUP BY owner;
SQL
EOF
USER app
ENTRYPOINT ["./tools/entrypoint.sh"]
CMD ["python", "-m", "app"]
