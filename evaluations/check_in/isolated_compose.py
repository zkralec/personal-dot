"""Write a credential-free Compose manifest; never starts or deletes resources."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"pd-eval-[a-z0-9-]+", args.project):
        parser.error("use a fresh project name starting with pd-eval-")
    root = Path(__file__).resolve().parents[2]
    # Do not resolve Compose substitutions from .env or inherited application settings.
    environment = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"}}
    resolved = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "--profile", "test", "-f", str(root / "compose.yaml"),
         "config", "--format", "json"],
        env=environment, check=True, capture_output=True, text=True,
    )
    manifest = json.loads(resolved.stdout)
    manifest["name"] = args.project
    manifest["networks"] = {"default": {"name": args.project + "_default", "internal": True}}
    for name, volume in manifest["volumes"].items():
        volume["name"] = args.project + "_" + name
    for service in manifest["services"].values():
        service.pop("ports", None)
        if "build" in service:
            service["build"]["context"] = str(root)
            service["image"] = args.project + ":local"
        settings = service.get("environment", {})
        for key in ("OPENAI_API_KEY", "PUSHOVER_API_TOKEN", "PUSHOVER_USER_KEY"):
            if key in settings:
                settings[key] = ""
        settings["RUN_OPENAI_INTEGRATION"] = "0"
        settings["RUN_CHECK_IN_LIVE_EVAL"] = "0"
    with args.output.open("x") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
