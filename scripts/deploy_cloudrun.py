"""Deploy WARRANT to Google Cloud Run (personal project, scale to zero).

    .venv/bin/python scripts/deploy_cloudrun.py

Always the PERSONAL gcloud account and project, passed on every call, never
the machine's active config (an employer account). Builds the same container
as the Hugging Face Space (deploy/hf/Dockerfile) with Cloud Build. Token Factory
credentials and the judge code go in as environment variables from a temp file
that is deleted straight after, so they are never on a command line, in the
image or in this repository.

One instance at most: the grant model, the audit log and the daily live-run
cap are in memory, so a second instance would disagree with the first. Scale
to zero means the first visit after idle waits for a cold start; the video and
the README say so.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from deploy_hf import _env

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = os.environ.get("DEPLOY_ACCOUNT", "junwei.lai@gmail.com")
PROJECT = os.environ.get("DEPLOY_PROJECT", "agent-era")
REGION = os.environ.get("DEPLOY_REGION", "us-central1")
SERVICE = "warrant"
SECRETS = ("WARRANT_TF_API_KEY", "WARRANT_TF_BASE_URL", "WARRANT_JUDGE_KEY")


def main() -> None:
    env = _env()
    missing = [k for k in SECRETS if not env.get(k)]
    if missing:
        raise SystemExit(f".env is missing {', '.join(missing)}")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        src = t / "src_ctx"
        shutil.copytree(ROOT / "src", src / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ROOT / "config", src / "config")
        for f in ("pyproject.toml", "README.md"):
            shutil.copy(ROOT / f, src / f)
        shutil.copy(ROOT / "deploy/hf/Dockerfile", src / "Dockerfile")
        for f in src.rglob("*"):
            if f.name == ".env" or f.suffix in (".pem", ".key"):
                raise SystemExit(f"refusing to upload {f}")
        envfile = t / "env.yaml"
        envfile.touch(mode=0o600)
        envfile.write_text("".join(f'{k}: "{env[k]}"\n' for k in SECRETS))
        subprocess.run([
            "gcloud", "run", "deploy", SERVICE, "--source", str(src),
            f"--account={ACCOUNT}", f"--project={PROJECT}", f"--region={REGION}",
            "--port=7860", "--allow-unauthenticated", "--min-instances=0",
            "--max-instances=1", "--memory=1Gi", "--cpu=1", "--timeout=900",
            f"--env-vars-file={envfile}", "--quiet"], check=True)
    url = subprocess.check_output([
        "gcloud", "run", "services", "describe", SERVICE, f"--account={ACCOUNT}",
        f"--project={PROJECT}", f"--region={REGION}", "--format=value(status.url)"]).decode().strip()
    print(f"\ndeployed: {url}\njudges' link: {url}/?key=<WARRANT_JUDGE_KEY from .env>")


if __name__ == "__main__":
    main()
