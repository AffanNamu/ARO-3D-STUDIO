// Runs the official Khronos glTF-Validator (npm "gltf-validator") on a .glb/.gltf file and prints a JSON summary.
// Usage: NODE_PATH=<dir containing node_modules> node khronos_validate.cjs <file>
const fs = require('fs');
const path = require('path');
const validator = require('gltf-validator');
const file = process.argv[2];
const data = new Uint8Array(fs.readFileSync(file));
validator
  .validateBytes(data, {
    uri: path.basename(file),
    externalResourceFunction: (uri) =>
      new Promise((resolve, reject) => {
        const p = path.resolve(path.dirname(file), decodeURIComponent(uri));
        if (!p.startsWith(path.resolve(path.dirname(file)))) return reject(new Error('path escapes directory'));
        fs.readFile(p, (e, d) => (e ? reject(e) : resolve(new Uint8Array(d))));
      }),
    maxIssues: 100,
  })
  .then((r) => {
    process.stdout.write(JSON.stringify({ version: validator.version(), issues: r.issues, info: { drawCallCount: r.info.drawCallCount, totalTriangleCount: r.info.totalTriangleCount, materialCount: r.info.materialCount } }));
  })
  .catch((e) => { process.stderr.write(String(e)); process.exit(2); });
