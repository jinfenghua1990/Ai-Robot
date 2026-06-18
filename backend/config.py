import os
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://airobot:airobot_dev_2026@localhost:5432/airobot")
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
API_PORT = int(os.getenv("API_PORT", "9000"))
