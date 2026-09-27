"""Entry point kept for compatibility: `python supercam.py` starts the FastAPI server.

Equivalent to: uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
"""
import logging
import os

import uvicorn

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("app.main:create_app", factory=True,
                host=os.environ.get("FRACS_HOST", "0.0.0.0"),
                port=int(os.environ.get("FRACS_PORT", "8000")))
