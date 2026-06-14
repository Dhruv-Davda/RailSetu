"""
Vercel serverless entry point.

@vercel/python serves the ASGI `app` exported here. The backend lives in
`backend/`, which `vercel.json` bundles via `includeFiles`; we put it on the path
so `from app.main import app` resolves the same way it does locally.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.main import app  # noqa: E402,F401  -- Vercel serves this ASGI `app`
