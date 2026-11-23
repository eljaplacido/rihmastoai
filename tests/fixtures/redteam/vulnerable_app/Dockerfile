# seeded below: RT-DOCKER-UNPINNED RT-DOCKER-ROOT
FROM python
WORKDIR /srv
# seeded below: RT-DOCKER-ADDURL
ADD https://downloads.example.org/tools/report-tool.tar.gz /tmp/report-tool.tar.gz
COPY app ./app
ENV PORT=8080 DATA_DIR=/data
EXPOSE 8080
CMD ["python3", "-m", "app.server"]
