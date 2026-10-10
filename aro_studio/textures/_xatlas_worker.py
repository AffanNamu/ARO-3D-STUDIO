"""Out-of-process xatlas runner.

xatlas is native code that was observed to segfault on large meshes (82k faces) with the pinned wheel.
Running it in a child process turns a hard crash into a normal, reportable error. Only numpy + xatlas are
imported here; run with ``python -I _xatlas_worker.py in.npz out.npz``.
"""

import sys

import numpy as np
import xatlas

if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with np.load(src, allow_pickle=False) as z:
        positions = z["positions"].astype(np.float32)
        indices = z["indices"].astype(np.uint32)
    vmapping, new_indices, uvs = xatlas.parametrize(positions, indices)
    np.savez(dst, vmapping=vmapping, indices=new_indices, uvs=uvs)
