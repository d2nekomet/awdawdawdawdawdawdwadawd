import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    hub_token: str
    admin_ids: frozenset[int]
    data_dir: Path
    sub_days: int
    stars_price: int
    enabled_payments: tuple[str, ...]
    cryptobot_token: str
    cryptobot_testnet: bool
    cryptobot_asset: str
    cryptobot_amount: str
    max_bots_per_user: int
    drive_upload_url: str
    drive_api_token: str
    translate_url: str
    translate_api_key: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "franchise.sqlite3"

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "Settings":
        if env_file:
            load_dotenv(env_file)
        get = os.environ.get
        return cls(
            hub_token=get("HUB_BOT_TOKEN", ""),
            admin_ids=frozenset(int(x) for x in _csv(get("ADMIN_IDS", ""))),
            data_dir=Path(get("DATA_DIR", "data")),
            sub_days=int(get("SUB_DAYS", "30")),
            stars_price=int(get("STARS_PRICE", "100")),
            enabled_payments=_csv(get("ENABLED_PAYMENTS", "stars")),
            cryptobot_token=get("CRYPTOBOT_TOKEN", ""),
            cryptobot_testnet=get("CRYPTOBOT_TESTNET", "false").lower() == "true",
            cryptobot_asset=get("CRYPTOBOT_ASSET", "USDT"),
            cryptobot_amount=get("CRYPTOBOT_AMOUNT", "1"),
            max_bots_per_user=int(get("MAX_BOTS_PER_USER", "3")),
            drive_upload_url=get("DRIVE_UPLOAD_URL", ""),
            drive_api_token=get("DRIVE_API_TOKEN", ""),
            translate_url=get("TRANSLATE_URL", "https://libretranslate.com/translate"),
            translate_api_key=get("TRANSLATE_API_KEY", ""),
        )
