import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv(
        "GROQ_MODEL",
        "llama-3.3-70b-versatile",
    )
    batch_size: int = 5
    max_retries: int = 5
    db_path: str = os.getenv("DB_PATH", "reviewlens.db")


settings = Settings()
