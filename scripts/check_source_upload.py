"""Read-only upload preflight. Never prints credential values or stages files."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def candidates():
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, check=True, capture_output=True)
    return sorted(set(p.decode("utf-8") for p in result.stdout.split(b"\0") if p))


def local_secrets():
    path = ROOT / "backend/.env.chat.local"
    if not path.exists():
        return []
    values = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() not in {"ELICE_API_KEY", "OPENAI_API_KEY"}:
            continue
        value = value.strip().strip("\"'")
        if len(value) >= 8:
            values.append(value.encode("utf-8"))
    return values


def main():
    patterns = {
        "openai_like_key": re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
        "github_like_key": re.compile(rb"(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}"),
        "private_key": re.compile(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "jwt_like_value": re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{15,}"),
    }
    secrets = local_secrets()
    rows, issues = [], []
    for name in candidates():
        path = ROOT / name
        if not path.is_file():
            continue
        if path.is_symlink():
            issues.append({"path": name, "rule": "symlink_requires_review"})
            continue
        parts = Path(name).parts
        if any(p in {"node_modules", ".git", "__pycache__", ".venv"} for p in parts):
            issues.append({"path": name, "rule": "generated_or_private_directory"})
        if path.name.startswith(".env") and not path.name.endswith(".example"):
            issues.append({"path": name, "rule": "private_environment_file"})
        blob = path.read_bytes()
        if any(secret in blob for secret in secrets):
            issues.append({"path": name, "rule": "local_credential_value"})
        if path.suffix.lower() not in {".woff2", ".png", ".jpg", ".jpeg", ".webp", ".pdf"}:
            for rule, pattern in patterns.items():
                if pattern.search(blob):
                    issues.append({"path": name, "rule": rule})
        if len(blob) > 30_000_000:
            issues.append({"path": name, "rule": "large_file_requires_review"})
        rows.append({"path": name, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()})
    manifest = {"scope_name": "source upload preflight",
                "scope": "current upload candidates; not a push receipt", "file_count": len(rows),
                "total_bytes": sum(r["bytes"] for r in rows), "issues": issues, "files": rows}
    out = ROOT / "docs/release/upload-manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, ensure_ascii=False))
    raise SystemExit(1 if issues else 0)


if __name__ == "__main__":
    main()
