#!/usr/bin/env bash
# Rebuild the page's vendored modules from the pinned versions in package.json.
#   misc/vendor/build.sh
# Writes annals/data/ui/vendor/zodal-store-http.min.js (commit it).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="$here/../../annals/data/ui/vendor"
cd "$here"
npm install --no-audit --no-fund --silent
mkdir -p "$out"
npx esbuild entry-zodal-store-http.js --bundle --minify --format=iife \
  --global-name=ZodalStoreHttp --target=es2019 \
  --banner:js="/* @zodal/store-http $(node -p "require('./node_modules/@zodal/store-http/package.json').version") (MIT), bundled for annals by misc/vendor/build.sh */" \
  --outfile="$out/zodal-store-http.min.js"
