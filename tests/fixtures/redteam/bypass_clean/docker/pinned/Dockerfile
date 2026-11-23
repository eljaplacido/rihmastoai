ARG BASE=python:3.12-slim
FROM ${BASE}
ARG RUN_AS=app
RUN useradd --create-home app && \
    curl -fsSLo /tmp/tool.tgz https://downloads.example.org/tool-1.2.3.tgz && \
    echo "0123456789abcdef  /tmp/tool.tgz" | sha256sum -c -
USER ${RUN_AS}
CMD ["python", "-c", "print('ok')"]
