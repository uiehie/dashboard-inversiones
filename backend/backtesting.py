"""
Motor de backtesting para estrategias simples de trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import yfinance as yf


@dataclass
class BacktestConfig:
    ticker: str
    period: str = "1y"
    initial_capital: float = 10000.0
    fast_window: int = 20
    slow_window: int = 50
    commission_pct: float = 0.1
    slippage_pct: float = 0.05


def _max_drawdown_pct(equity_curve: List[float]) -> float:
    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    max_drawdown = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return round(max_drawdown * 100, 2)


def _annualized_return_pct(initial_capital: float, final_capital: float, days: int) -> float:
    if initial_capital <= 0 or final_capital <= 0 or days <= 0:
        return 0.0

    years = days / 365.0
    if years <= 0:
        return 0.0

    total_growth = final_capital / initial_capital
    annualized = (total_growth ** (1 / years)) - 1
    return round(annualized * 100, 2)


def _run_buy_hold(prices: List[float], config: BacktestConfig) -> Dict:
    if not prices:
        return {
            "final_capital": round(config.initial_capital, 2),
            "return_pct": 0.0,
        }

    first_price = prices[0] * (1 + config.slippage_pct / 100)
    if first_price <= 0:
        return {
            "final_capital": round(config.initial_capital, 2),
            "return_pct": 0.0,
        }

    cash = config.initial_capital
    shares = cash / first_price
    buy_commission = cash * (config.commission_pct / 100)
    cash -= buy_commission

    final_capital = cash + shares * prices[-1]
    return_pct = ((final_capital - config.initial_capital) / config.initial_capital) * 100 if config.initial_capital > 0 else 0

    return {
        "final_capital": round(final_capital, 2),
        "return_pct": round(return_pct, 2),
    }


def run_sma_crossover_backtest(config: BacktestConfig) -> Dict:
    ticker = yf.Ticker(config.ticker.upper())
    hist = ticker.history(period=config.period, interval="1d")

    if hist.empty:
        raise ValueError("No hay datos historicos para el ticker o periodo seleccionado")

    hist = hist[["Close"]].dropna().copy()
    hist["sma_fast"] = hist["Close"].rolling(window=config.fast_window).mean()
    hist["sma_slow"] = hist["Close"].rolling(window=config.slow_window).mean()

    # Posicion objetivo: 1 cuando sma_fast > sma_slow, 0 en caso contrario
    hist["target_position"] = (hist["sma_fast"] > hist["sma_slow"]).astype(int).shift(1).fillna(0)

    prices = hist["Close"].tolist()
    dates = [idx.strftime("%Y-%m-%d") for idx in hist.index]
    target_positions = hist["target_position"].tolist()

    cash = config.initial_capital
    shares = 0.0

    equity_curve: List[float] = []
    trades: List[Dict] = []
    entry_value = 0.0

    for i, price in enumerate(prices):
        target = int(target_positions[i])

        if target == 1 and shares == 0 and cash > 0:
            buy_price = price * (1 + config.slippage_pct / 100)
            trade_value = cash
            commission = trade_value * (config.commission_pct / 100)
            net_invested = max(trade_value - commission, 0)
            shares = net_invested / buy_price if buy_price > 0 else 0
            cash = 0.0
            entry_value = trade_value

            trades.append(
                {
                    "fecha": dates[i],
                    "tipo": "BUY",
                    "precio": round(buy_price, 2),
                    "comision": round(commission, 2),
                }
            )

        elif target == 0 and shares > 0:
            sell_price = price * (1 - config.slippage_pct / 100)
            gross_value = shares * sell_price
            commission = gross_value * (config.commission_pct / 100)
            net_value = max(gross_value - commission, 0)
            cash = net_value

            pnl = net_value - entry_value
            pnl_pct = (pnl / entry_value * 100) if entry_value > 0 else 0

            trades.append(
                {
                    "fecha": dates[i],
                    "tipo": "SELL",
                    "precio": round(sell_price, 2),
                    "comision": round(commission, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                }
            )

            shares = 0.0
            entry_value = 0.0

        portfolio_value = cash + (shares * price)
        equity_curve.append(portfolio_value)

    final_capital = equity_curve[-1] if equity_curve else config.initial_capital
    total_return_pct = ((final_capital - config.initial_capital) / config.initial_capital) * 100 if config.initial_capital > 0 else 0

    closed_trade_results = [t for t in trades if t["tipo"] == "SELL"]
    total_closed = len(closed_trade_results)
    wins = len([t for t in closed_trade_results if t.get("pnl", 0) > 0])
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0

    benchmark = _run_buy_hold(prices, config)

    curve_points = [
        {"fecha": dates[i], "valor": round(equity_curve[i], 2)}
        for i in range(len(equity_curve))
    ]

    return {
        "ticker": config.ticker.upper(),
        "periodo": config.period,
        "estrategia": "SMA_Crossover",
        "parametros": {
            "capital_inicial": config.initial_capital,
            "sma_rapida": config.fast_window,
            "sma_lenta": config.slow_window,
            "comision_pct": config.commission_pct,
            "slippage_pct": config.slippage_pct,
        },
        "resultado": {
            "capital_final": round(final_capital, 2),
            "retorno_total_pct": round(total_return_pct, 2),
            "retorno_anualizado_pct": _annualized_return_pct(config.initial_capital, final_capital, len(prices)),
            "max_drawdown_pct": _max_drawdown_pct(equity_curve),
            "trades_cerrados": total_closed,
            "win_rate_pct": round(win_rate, 2),
        },
        "benchmark_buy_hold": benchmark,
        "equity_curve": curve_points,
        "trades": trades,
    }
