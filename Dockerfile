FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

# [agents] matters: /v1/demo/run builds the LangGraph auditor, and the console's
# Run button calls it. Installing bare `.` left langgraph out, so the shipped
# image served a console whose primary action raised ImportError.
RUN pip install --no-cache-dir -e ".[agents]"

ENV WARRANT_CONFIG=config/warrant.yaml
# The audit log is also the warrant store, so it needs somewhere durable. The
# config falls back to this same relative path when the variable is unset, but
# naming it here makes the mount point obvious.
ENV WARRANT_AUDIT_PATH=/app/audit/warrant.jsonl
RUN mkdir -p /app/audit
VOLUME ["/app/audit"]

# The container will NOT start without Token Factory credentials - both tiers
# are configured to use them and a tier with no base_url is a hard failure
# rather than a silent fallback to a stub:
#   docker run -e WARRANT_TF_API_KEY=... -e WARRANT_TF_BASE_URL=... -p 8000:8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()" || exit 1
CMD ["uvicorn", "warrant.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
