from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    instrument: str = "EURUSD"
    timeframe: str = "M15"
    log_level: str = "INFO"
    log_file: str = "trading_system.log"
    mock_data: bool = True
    mock_scenario: str = "bullish"
    max_strategy_retries: int = 3
    model: str = "claude-sonnet-4-6"
    stop_loss_pips: int = 10
    take_profit_pips: int = 20
    breakeven_trigger_pips: int = 10
    trailing_distance_pips: int = 10
    poll_interval_seconds: float = 5.0

    class Config:
        env_file = ".env"


settings = Settings()
