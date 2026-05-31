from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Anthropic ─────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    model: str = "claude-sonnet-4-6"

    # ── Instrument / timeframe ─────────────────────────────────────────────────
    instrument: str = "EURUSD"
    timeframe: str = "M15"

    # ── Risk rules (hard) ────────────────────────────────────────────────────
    stop_loss_pips: int = 10
    take_profit_pips: int = 20
    breakeven_trigger_pips: int = 10
    trailing_distance_pips: int = 10

    # ── Live vs mock ──────────────────────────────────────────────────────────
    live_trading: bool = False          # False = use mock data/broker
    mock_scenario: str = "bullish"      # only used when live_trading=False

    # ── MT5 connection (only needed when live_trading=True) ───────────────────
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = "XM-Demo"         # e.g. XM-Real, XM-Real 2, XM-Demo
    mt5_symbol: str = ""                # leave empty to auto-use instrument
    mt5_lot_size: float = 0.01          # minimum safe lot for testing
    mt5_magic: int = 20240001           # unique identifier for bot orders

    # ── Pipeline ──────────────────────────────────────────────────────────────
    max_strategy_retries: int = 3
    poll_interval_seconds: float = 5.0  # how often risk manager checks trade

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "trading_system.log"

    class Config:
        env_file = ".env"

    @property
    def mt5_symbol_name(self) -> str:
        """The MT5 symbol to use — falls back to instrument if not set."""
        return self.mt5_symbol or self.instrument


settings = Settings()
