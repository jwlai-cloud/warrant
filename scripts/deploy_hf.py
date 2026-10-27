"""Deploy WARRANT to a Hugging Face Docker Space.

    .venv/bin/hf auth login            # once, with a WRITE token
    .venv/bin/python scripts/deploy_hf.py [--space jwlai-cloud/warrant]

Creates the Space if needed, stores the Token Factory credentials as Space
SECRETS (read from .env, never printed, never committed), and uploads only what
the image needs. Re-running redeploys.
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ("WARRANT_TF_API_KEY", "WARRANT_TF_BASE_URL", "WARRANT_JUDGE_KEY")


def _env() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default=None, help="owner/name; defaults to <you>/warrant")
    args = ap.parse_args()

    api = HfApi()
    me = api.whoami()["name"]
    space = args.space or f"{me}/warrant"

    env = _env()
    missing = [k for k in SECRETS if not env.get(k)]
    if missing:
        raise SystemExit(f".env is missing {', '.join(missing)}")

    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    for k in SECRETS:
        api.add_space_secret(space, k, env[k])          # value never echoed
    print(f"secrets set on {space}: {', '.join(SECRETS)}")

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        shutil.copytree(ROOT / "src", t / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ROOT / "config", t / "config")
        shutil.copy(ROOT / "pyproject.toml", t / "pyproject.toml")
        shutil.copy(ROOT / "deploy/hf/Dockerfile", t / "Dockerfile")
        shutil.copy(ROOT / "deploy/hf/README.md", t / "README.md")
        # belt and braces: nothing secret in what we upload
        for f in t.rglob("*"):
            if f.name == ".env" or f.suffix in (".pem", ".key"):
                raise SystemExit(f"refusing to upload {f}")
        api.upload_folder(folder_path=tmp, repo_id=space, repo_type="space",
                          commit_message="Deploy WARRANT")

    print(f"\ndeployed. building now - watch it at https://huggingface.co/spaces/{space}")
    print(f"app URL once built: https://{space.replace('/', '-').lower()}.hf.space")


if __name__ == "__main__":
    main()
