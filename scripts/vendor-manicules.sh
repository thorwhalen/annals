#!/bin/sh
# Copy manicules' built widget into annals' page assets, where a document's page loads it
# (highlights: annals/highlights.py is the server side).
# Usage: scripts/vendor-manicules.sh [path to a built manicules checkout]
#   (build it first: npm ci && npm run build, in that checkout)
# Beside the script and its stylesheet go the JSON Schema and the conformance vectors the
# server's tests are held to, the licence and third-party notices of what the script
# bundles, and SOURCE.json: the commit, the version and a sha256 of each file, which
# tests/test_highlights.py checks, so a hand edit or a half copy does not pass.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
src=${1:-"$here/../../tt/manicules"}
dst="$here/annals/data/ui/vendor/manicules"
mkdir -p "$dst"
cp "$src/dist/manicules.global.js" "$src/dist/styles.css" "$src/dist/highlight.schema.json" "$src/dist/conformance.json" "$dst/"
cp "$src/LICENSE" "$dst/LICENSE"
cp "$src/THIRD_PARTY_NOTICES.md" "$dst/THIRD_PARTY_NOTICES.md"
python3 - "$src" "$dst" <<'PY'
import hashlib, json, pathlib, subprocess, sys
src, dst = map(pathlib.Path, sys.argv[1:])
files = sorted(p.name for p in dst.iterdir() if p.is_file() and p.name != "SOURCE.json" and not p.name.startswith("."))
manifest = {
    "package": "manicules",
    "version": json.loads((src / "package.json").read_text())["version"],
    "commit": subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip(),
    "repository": "https://github.com/thorwhalen/manicules",
    "sha256": {name: hashlib.sha256((dst / name).read_bytes()).hexdigest() for name in files},
}
(dst / "SOURCE.json").write_text(json.dumps(manifest, indent=1) + "\n")
print("vendored manicules", manifest["version"], manifest["commit"][:7], "-", len(files), "files")
PY
