from typing import Any

from agents import BaseAgent
from tools.risk_tools import RISK_TOOLS, calculate_trailing_stop_tool, get_pnl_tool, check_risk_conditions_tool
from tools.trading_tools import TRADING_TOOLS, MockBroker

_SYSTEM_PROMPT = """
You are the Risk Manager Agent. You monitor open trades and manage risk in real-time.

RESPONSIBILITIES:
1. Get current trade status and P&L using get_pnl
2. Calculate trailing stop using calculate_trailing_stop
3. If SL moved: call modify_stop_loss (only if new_sl is better than current)
4. Check risk conditions using check_risk_conditions
5. If conditions say close: call close_trade

TRAILING STOP RULES:
- When profit >= 10 pips: SL moves to entry (breakeven) and trailing begins
- SL trails 10 pips behind current price
- For BUY: SL only moves UP (never backwards)
- For SELL: SL only moves DOWN (never backwards)

CLOSE TRADE CONDITIONS:
- P&L <= -10 pips (stop loss hit)
- P&L >= 20 pips (take profit hit)
- check_risk_conditions returns should_close = true
- Trade has been open > 4 hours (mock limit)

Respond ONLY with a JSON object:
{
  "trade_id": "string",
  "action": "modify_sl" | "close_trade" | "no_action",
  "current_price": <float>,
  "current_pnl_pips": <float>,
  "current_sl": <float>,
  "breakeven_activated": true | false,
  "trailing_active": true | false,
  "trade_status": "open" | "closed",
  "close_reason": "string or null",
  "reasoning": "what was done and why"
}
""".strip()

_ALL_TOOLS = RISK_TOOLS + [t for t in TRADING_TOOLS if t["name"] in {"modify_stop_loss", "close_trade", "get_trade_status"}]


class RiskManagerAgent(BaseAgent):
    def __init__(self, settings, broker: MockBroker):
        super().__init__(
            name="RiskManager",
            system_prompt=_SYSTEM_PROMPT,
            tools=_ALL_TOOLS,
            model=settings.model,
            api_key=settings.anthropic_api_key,
        )
        self.broker = broker
        self.settings = settings

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "calculate_trailing_stop":
            return calculate_trailing_stop_tool(
                instrument=tool_input["instrument"],
                direction=tool_input["direction"],
                entry_price=tool_input["entry_price"],
                current_price=tool_input["current_price"],
                current_sl=tool_input["current_sl"],
                breakeven_activated=tool_input["breakeven_activated"],
                trailing_distance_pips=tool_input.get(
                    "trailing_distance_pips", self.settings.trailing_distance_pips
                ),
                breakeven_trigger_pips=tool_input.get(
                    "breakeven_trigger_pips", self.settings.breakeven_trigger_pips
                ),
            )
        if tool_name == "get_pnl":
            return get_pnl_tool(
                instrument=tool_input["instrument"],
                direction=tool_input["direction"],
                entry_price=tool_input["entry_price"],
                current_price=tool_input["current_price"],
            )
        if tool_name == "check_risk_conditions":
            return check_risk_conditions_tool(
                trade_id=tool_input["trade_id"],
                pnl_pips=tool_input["pnl_pips"],
                open_duration_minutes=tool_input["open_duration_minutes"],
                current_price=tool_input["current_price"],
                current_sl=tool_input["current_sl"],
                current_tp=tool_input["current_tp"],
                direction=tool_input["direction"],
            )
        if tool_name == "get_trade_status":
            return self.broker.get_trade_status(trade_id=tool_input["trade_id"])
        if tool_name == "modify_stop_loss":
            return self.broker.modify_stop_loss(
                trade_id=tool_input["trade_id"],
                new_stop_loss=tool_input["new_stop_loss"],
            )
        if tool_name == "close_trade":
            return self.broker.close_trade(
                trade_id=tool_input["trade_id"],
                reason=tool_input["reason"],
            )
        raise ValueError(f"Unknown tool: {tool_name}")

    def build_prompt(self, trade_snapshot: dict) -> str:
        import json
        return (
            f"Monitor and manage this open trade. Apply trailing stop rules and "
            f"close if conditions are met.\n\n"
            f"TRADE STATE:\n{json.dumps(trade_snapshot, indent=2, default=str)}"
        )
