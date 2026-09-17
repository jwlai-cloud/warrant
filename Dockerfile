FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir -e .
ENV WARRANT_CONFIG=config/warrant.yaml
EXPOSE 8000
CMD ["uvicorn", "warrant.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
