#!/bin/sh
# Copy @zodal/speech's built player into annals' page assets, where audio documents load it.
# Usage: scripts/vendor-zodal-speech.sh [path to a built zodal-speech checkout]
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
src=${1:-"$here/../../i/_zodals/zodal-speech"}
dst="$here/annals/data/ui/vendor/zodal-speech"
mkdir -p "$dst"
cp "$src/dist/player.iife.js" "$src/dist/styles.css" "$dst/"
git -C "$src" rev-parse HEAD > "$dst/SOURCE_COMMIT"
