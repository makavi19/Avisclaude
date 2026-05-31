INSTRUMENT_PIP_SIZES: dict[str, float] = {
    # Standard forex
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001,
    "NZDUSD": 0.0001, "USDCAD": 0.0001, "USDCHF": 0.0001,
    "EURGBP": 0.0001, "EURAUD": 0.0001, "EURCHF": 0.0001,
    "EURCAD": 0.0001, "GBPAUD": 0.0001, "GBPCAD": 0.0001,
    "AUDCAD": 0.0001, "AUDCHF": 0.0001, "AUDNZD": 0.0001,
    "GBPNZD": 0.0001, "EURNZD": 0.0001,
    # JPY pairs
    "USDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01,
    "AUDJPY": 0.01, "CADJPY": 0.01, "CHFJPY": 0.01,
    "NZDJPY": 0.01,
    # Metals
    "XAUUSD": 0.10, "XAGUSD": 0.001,
    # Indices
    "US30": 1.0, "NAS100": 1.0, "SPX500": 0.1,
    "UK100": 1.0, "GER40": 1.0, "FRA40": 1.0, "JPN225": 1.0,
    # Crypto
    "BTCUSD": 1.0, "ETHUSD": 0.01,
}


def normalize_instrument(instrument: str) -> str:
    return instrument.upper().replace("/", "").replace("-", "").replace("_", "").replace(".", "")


def get_pip_size(instrument: str) -> float:
    key = normalize_instrument(instrument)
    if key in INSTRUMENT_PIP_SIZES:
        return INSTRUMENT_PIP_SIZES[key]
    if key.endswith("JPY"):
        return 0.01
    if any(key.startswith(x) for x in ["BTC", "ETH", "LTC", "XRP"]):
        return 1.0
    return 0.0001


def get_price_decimals(instrument: str) -> int:
    pip_size = get_pip_size(instrument)
    if pip_size >= 1.0:
        return 1
    if pip_size >= 0.1:
        return 2
    if pip_size >= 0.01:
        return 3
    return 5


def pips_to_price(pips: float, instrument: str) -> float:
    return pips * get_pip_size(instrument)


def price_to_pips(price_distance: float, instrument: str) -> float:
    pip_size = get_pip_size(instrument)
    return abs(price_distance) / pip_size


def calculate_sl_price(entry: float, direction: str, pips: float, instrument: str) -> float:
    distance = pips_to_price(pips, instrument)
    decimals = get_price_decimals(instrument)
    if direction.lower() == "buy":
        return round(entry - distance, decimals)
    return round(entry + distance, decimals)


def calculate_tp_price(entry: float, direction: str, pips: float, instrument: str) -> float:
    distance = pips_to_price(pips, instrument)
    decimals = get_price_decimals(instrument)
    if direction.lower() == "buy":
        return round(entry + distance, decimals)
    return round(entry - distance, decimals)


def compute_trailing_stop(
    instrument: str,
    direction: str,
    entry_price: float,
    current_price: float,
    current_sl: float,
    breakeven_activated: bool,
    trailing_distance_pips: float = 10.0,
    breakeven_trigger_pips: float = 10.0,
) -> dict:
    pip_size = get_pip_size(instrument)
    trailing_dist = trailing_distance_pips * pip_size
    # Small epsilon avoids float precision misses (e.g. 0.00099999 < 0.001)
    _eps = pip_size * 0.01
    be_trigger = breakeven_trigger_pips * pip_size
    decimals = get_price_decimals(instrument)

    if direction == "buy":
        pnl_dist = current_price - entry_price

        if not breakeven_activated and pnl_dist >= be_trigger - _eps:
            # Move SL to entry, start trailing
            candidate = current_price - trailing_dist
            new_sl = round(max(current_sl, candidate, entry_price), decimals)
            return {
                "new_sl": new_sl,
                "breakeven_activated": True,
                "trailing_active": True,
                "sl_moved": new_sl > current_sl,
                "action_taken": "breakeven_and_trailing_activated",
            }

        if breakeven_activated:
            candidate = current_price - trailing_dist
            new_sl = round(max(current_sl, candidate), decimals)
            moved = new_sl > current_sl
            return {
                "new_sl": new_sl,
                "breakeven_activated": True,
                "trailing_active": True,
                "sl_moved": moved,
                "action_taken": "trailing_updated" if moved else "no_change",
            }

    elif direction == "sell":
        pnl_dist = entry_price - current_price

        if not breakeven_activated and pnl_dist >= be_trigger - _eps:
            candidate = current_price + trailing_dist
            new_sl = round(min(current_sl, candidate, entry_price), decimals)
            return {
                "new_sl": new_sl,
                "breakeven_activated": True,
                "trailing_active": True,
                "sl_moved": new_sl < current_sl,
                "action_taken": "breakeven_and_trailing_activated",
            }

        if breakeven_activated:
            candidate = current_price + trailing_dist
            new_sl = round(min(current_sl, candidate), decimals)
            moved = new_sl < current_sl
            return {
                "new_sl": new_sl,
                "breakeven_activated": True,
                "trailing_active": True,
                "sl_moved": moved,
                "action_taken": "trailing_updated" if moved else "no_change",
            }

    return {
        "new_sl": current_sl,
        "breakeven_activated": breakeven_activated,
        "trailing_active": False,
        "sl_moved": False,
        "action_taken": "no_change",
    }
