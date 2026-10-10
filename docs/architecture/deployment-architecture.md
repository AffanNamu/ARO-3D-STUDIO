# Deployment architecture

The Studio is one container exposing port 7860 (`Dockerfile`). It is portable: nothing depends on Hugging Face except the optional weights download.

| Target | Notes |
|---|---|
| **Hugging Face Space (Docker SDK), free CPU** | initial target; see [huggingface.md](../deployment/huggingface.md). Ephemeral disk; no free GPU for Docker Spaces (limitation documented, not hidden). |
| Local machine with an NVIDIA GPU | `pip install -r requirements.txt`, torch + TripoSR extras, `uvicorn app:app`. Best path for real reconstruction at ₦0. |
| Any Docker host | `docker build [--build-arg WITH_TRIPOSR=1 …] .` |
| Free notebook GPUs (Colab/Kaggle) | run TripoSR there, download the mesh, **Import mesh** into the Studio (the Studio has no dependency on where the mesh came from). |

State lives in `ARO_DATA_DIR` (SQLite + files). On free Spaces this directory is **not persistent**: export projects (`Projects → Export project`) or exports you want to keep. Persistent storage is a paid Hugging Face feature and is not enabled automatically.

See also [infrastructure.md](../deployment/infrastructure.md).
