from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://airobot@localhost:5432/airobot")
V2_HOST = os.getenv("V2_HOST", "0.0.0.0")
V2_PORT = int(os.getenv("V2_PORT", "9001"))
V2_CACHE_SECONDS = int(os.getenv("V2_CACHE_SECONDS", "180"))
V2_RESEARCH_LIMIT = int(os.getenv("V2_RESEARCH_LIMIT", "300"))

# New program is read-only by default.  Real orders require both this flag and
# an explicit confirmation in the API request.
V2_TRADING_ENABLED = os.getenv("V2_TRADING_ENABLED", "false").lower() == "true"
V2_TRADING_APIKEY = os.getenv("V2_TRADING_APIKEY") or os.getenv("MX_APIKEY", "")
MX_API_URL = os.getenv("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")
