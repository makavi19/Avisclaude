from typing import Any

from agents import BaseAgent
from tools.trading_tools import TRADING_TOOLS, MockBroker

_SYSTEM_PROMPT = """
You are the Trade Execution Agent. You execute trades with precision.

HARD RULES — NEVER VIOLATE:
- Stop Loss: ALWAYS exactly 10 pips from entry
- Take Profit: ALWAYS exactly 20 pips from entry (1:2 risk-reward)
- For BUY: use the ask price; for SELL: use the bid price

EXECUTION PROCEDURE:
1. Call calculate_trade_levels with the instrument, direction, and entry price
   (this enforces the 10/20 pip rule automatically)
2. Call place_order with the computed levels
3. Report slippage if actual fill > 3 pips from expected

SLIPPAGE HANDLING:
- Slippage > 10 pips → do NOT execute; return status "failed" with reason
- Slippage <= 10 pips → execute and note in execution_notes

Respond ONLY with a JSON object:
{
  "trade_id": "string",
  "instrument": "string",
  "direction": "buy" | "sell",
  "entry_price": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "lot_size": <float>,
  "status": "placed" | "failed",
  "slippage_pips": <float>,
  "execution_notes": "string"
}
""".strip()


class ExecutionAgent(BaseAgent):
    def __init__(self, settings, broker: MockBroker):
        super().__init__(
            name="ExecutionAgent",
            system_prompt=_SYSTEM_PROMPT,
            tools=TRADING_TOOLS,
            model=settings.model,
            api_key=settings.anthropic_api_key,
        )
        self.broker = broker
        self.settings = settings

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "calculate_trade_levels":
            return self.broker.calculate_trade_levels(
                instrument=tool_input["instrument"],
                direction=tool_input["direction"],
                entry_price=tool_input["entry_price"],
                sl_pips=tool_input.get("sl_pips", self.settings.stop_loss_pips),
                tp_pips=tool_input.get("tp_pips", self.settings.take_profit_pips),
            )
        if tool_name == "place_order":
            return self.broker.place_order(
                instrument=tool_input["instrument"],
                direction=tool_input["direction"],
                entry_price=tool_input["entry_price"],
                stop_loss=tool_input["stop_loss"],
                take_profit=tool_input["take_profit"],
                lot_size=tool_input.get("lot_size", 0.1),
                strategy_name=tool_input.get("strategy_name", "unknown"),
            )
        if tool_name == "get_trade_status":
            return self.broker.get_trade_status(trade_id=tool_input["trade_id"])
        if tool_name == "close_trade":
            return self.broker.close_trade(
                trade_id=tool_input["trade_id"],
                reason=tool_input["reason"],
            )
        if tool_name == "modify_stop_loss":
            return self.broker.modify_stop_loss(
                trade_id=tool_input["trade_id"],
                new_stop_loss=tool_input["new_stop_loss"],
            )
        raise ValueError(f"Unknown tool: {tool_name}")

    def build_prompt(self, instrument: str, direction: str, strategy_name: str) -> str:
        return (
            f"Execute a {direction.upper()} trade on {instrument} "
            f"using strategy '{strategy_name}'. "
            f"Use calculate_trade_levels to get exact SL/TP (10 pip SL, 20 pip TP), "
            f"then place_order to execute. Report all details."
        )
