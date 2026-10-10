#!/usr/bin/env bash
# Rebuilds aro_studio/ui/static/vendor/three-viewer.min.js from pinned npm packages (three.js is MIT licensed).
# Requires Node.js + npm. The built file is committed so the Studio itself needs no Node at runtime.
set -euo pipefail
THREE_VERSION="${THREE_VERSION:-0.186.1}"
ESBUILD_VERSION="${ESBUILD_VERSION:-0.25.0}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"
npm init -y >/dev/null
npm i "three@${THREE_VERSION}" "esbuild@${ESBUILD_VERSION}" >/dev/null
cat > entry.js <<'JS'
export * from 'three';
export { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
export { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
export { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
JS
npx esbuild entry.js --bundle --minify --format=esm --target=es2020 --legal-comments=none --outfile="$HERE/aro_studio/ui/static/vendor/three-viewer.min.js"
cp node_modules/three/LICENSE "$HERE/aro_studio/ui/static/vendor/THREE-LICENSE.txt"
echo "three@${THREE_VERSION} bundled."
