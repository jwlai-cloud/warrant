# Hugging Face Docker Space build of WARRANT: the authorization plane, the
# console and the Expense Auditor in one container.
#
# Inference does NOT run here. Every model call goes to Nebius Token Factory
# (NVIDIA Nemotron), which is what the hackathon's eligibility rule asks for;
# this container only hosts the plane and the UI a judge opens.
FROM python:3.12-slim

# HF runs the container as UID 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR $HOME/app

COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src ./src
COPY --chown=user config ./config
RUN pip install --no-cache-dir --user ".[agents]"

# State lives in the container and resets when the Space restarts, which is
# also what the console's Reset button does. That is acceptable for a demo and
# would not be for anything else.
ENV WARRANT_CONFIG=config/warrant.yaml \
    WARRANT_AUDIT_PATH=/home/user/app/audit/warrant.jsonl
RUN mkdir -p /home/user/app/audit

# WARRANT_TF_API_KEY and WARRANT_TF_BASE_URL are Space SECRETS, injected at
# runtime. They are never in this image or this repository.
EXPOSE 7860
CMD ["uvicorn", "warrant.api.app:app", "--host", "0.0.0.0", "--port", "7860"]
