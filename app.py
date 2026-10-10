"""Entry point: ``uvicorn app:app`` (Hugging Face Spaces / Docker / local)."""

from aro_studio.api.app import create_app

app = create_app()

if __name__ == "__main__":  # pragma: no cover
    import os

    import uvicorn

    uvicorn.run("app:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "7860")))  # noqa: S104
