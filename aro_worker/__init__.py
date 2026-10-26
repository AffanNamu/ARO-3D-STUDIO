"""ARO GPU worker: runs heavy image-to-3D engines on a GPU host and serves them to the Studio over HTTP.

The Studio (UI, preparation, validation, export) stays light and can run anywhere; the models need a matching CUDA toolchain and a
24 GB-class GPU, so they live here, in their own environment. Self-contained: nothing in this package imports ``aro_studio``.
"""

PROTOCOL = 1
