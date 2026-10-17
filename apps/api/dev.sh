#!/bin/bash
uv run uvicorn app.main:app --reload --reload-dir app --port 8000
