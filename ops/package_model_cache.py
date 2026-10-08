"""Package only configured pinned HF snapshots and their referenced blobs.

HF token files, unrelated cached models and lock directories are never included.
Run after weight-backed smoke tests, outside the daily deadline path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

import yaml


def package(cache_root: Path, model_config: Path, output: Path):
    cache_root = cache_root.resolve()
    hub = cache_root / "hub"
    models = yaml.safe_load(model_config.read_text(encoding="utf-8"))
    members = {}
    evidence = []
    for model in models:
        if model.get("kind") != "tsfm" or not model.get("enabled"):
            continue
        revision = model["hf_revision"]
        snapshot = hub / ("models--" + model["hf_repo"].replace("/", "--")) / "snapshots" / revision
        if not snapshot.is_dir():
            raise ValueError(f"pinned snapshot missing: {model['id']}@{revision}")
        for path in snapshot.rglob("*"):
            if not path.is_file():
                continue
            target = path.resolve(strict=True)
            if not target.is_relative_to(hub.resolve()):
                raise ValueError("snapshot points outside the HF hub cache")
            members[str(path.relative_to(cache_root))] = path
            if path.is_symlink():
                members[str(target.relative_to(cache_root))] = target
        evidence.append({"id": model["id"], "hf_repo": model["hf_repo"], "revision": revision})
    if not evidence:
        raise ValueError("no enabled TSFM snapshots to package")
    if output.exists() or output.with_suffix(output.suffix + ".json").exists():
        raise FileExistsError("cache bundles are immutable; choose a new name")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "x:gz", dereference=False) as archive:
        for name, path in sorted(members.items()):
            archive.add(path, arcname=name.replace("\\", "/"), recursive=False)
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"archive": output.name, "sha256": digest, "models": evidence,
                "file_count": len(members), "archive_bytes": output.stat().st_size}
    output.with_suffix(output.suffix + ".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True, help="HF_HOME containing hub/")
    parser.add_argument("--models", type=Path, default=Path("pipeline/tsfm_live/config/models.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.cache, args.models, args.output)))
