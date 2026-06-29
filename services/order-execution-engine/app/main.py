import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from trading_shared.broker.angel_one.exceptions import AngelOneAPIError, AngelOneAuthError
from trading_shared.config import get_settings
from trading_shared.db.session import get_db, init_db
from trading_shared.execution.auto_trading import AutoTradingRunner, AutoTradingStore
from trading_shared.execution.executor import OrderExecutor, OrderRejectedError
from trading_shared.execution.paper import PaperTradeExecutor
from trading_shared.execution.trading_mode import MODE_LIVE, MODE_PAPER, TradingModeStore
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import User, UserRole
from trading_shared.risk.manager import RiskManager
from trading_shared.schemas.auto_trading import AutoTradingConfigUpdate
from trading_shared.schemas.order import (
    OrderCancelRequest,
    OrderCreateRequest,
    OrderModifyRequest,
    OrderResponse,
    TradingModeRequest,
)
from trading_shared.service_factory import create_service_app, register_ready_health

logger = logging.getLogger(__name__)
app = create_service_app("order-execution-engine", "Risk-gated live and paper order execution")
register_ready_health(app, "order-execution-engine", redis_required=True)
router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


async def _async_broker_connected(db, user_id: int) -> bool:
    executor = OrderExecutor(db, user_id)
    try:
        await executor.session_manager.get_client_for_user(user_id)
        return True
    except AngelOneAuthError:
        return False


@router.get("/status")
async def status(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    mode = TradingModeStore(get_settings().REDIS_URL).get(user.id)
    broker_ok = await _async_broker_connected(db, user.id)
    executor = OrderExecutor(db, user.id)
    risk = executor.risk.status()
    can_trade_risk = bool(risk.get("can_trade"))
    return {
        "status": "ok",
        "phase": 8,
        "trading_mode": mode,
        "broker_connected": broker_ok,
        "can_trade": can_trade_risk and (mode == MODE_PAPER or broker_ok),
        "can_trade_paper": can_trade_risk,
        "can_trade_live": can_trade_risk and broker_ok,
        "risk_status": risk.get("status"),
    }


@router.put("/mode")
async def set_trading_mode(
    payload: TradingModeRequest,
    db=Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    mode = payload.mode.lower().strip()
    if mode not in (MODE_PAPER, MODE_LIVE):
        raise HTTPException(status_code=400, detail="mode must be 'paper' or 'live'")

    if mode == MODE_LIVE and not await _async_broker_connected(db, user.id):
        raise HTTPException(
            status_code=400,
            detail="Connect Angel One before switching to live trading",
        )

    TradingModeStore(get_settings().REDIS_URL).set(user.id, mode)
    return {"trading_mode": mode, "message": f"Switched to {mode} trading"}


@router.get("/auto")
def get_auto_trading(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    runner = AutoTradingRunner(db, get_settings().REDIS_URL)
    return runner.status_for_user(user.id)


@router.put("/auto")
async def update_auto_trading(
    payload: AutoTradingConfigUpdate,
    db=Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    store = AutoTradingStore(get_settings().REDIS_URL)
    updates = payload.model_dump(exclude_none=True)

    if updates.get("enabled") is True:
        mode = TradingModeStore(get_settings().REDIS_URL).get(user.id)
        if mode == MODE_LIVE and not await _async_broker_connected(db, user.id):
            raise HTTPException(
                status_code=400,
                detail="Connect Angel One or switch to paper trading before enabling auto-trading in live mode",
            )
        if not updates.get("engine"):
            raise HTTPException(status_code=400, detail="engine is required when enabling or disabling auto-trading")
        merged = store.get_config(user.id)
        engine_cfg = merged["engine_settings"].get(updates["engine"], {})
        amount = float(engine_cfg.get("max_order_amount") or 0)
        if updates.get("max_order_amount") is not None:
            amount = float(updates["max_order_amount"])
        if amount <= 0:
            raise HTTPException(
                status_code=400,
                detail="Set max order amount (₹) before enabling auto-trading for this engine",
            )

    config = store.save_config(user.id, updates)
    risk = RiskManager(get_settings().REDIS_URL)
    risk.update_limits(max_daily_loss_pct=config.get("max_daily_loss_pct"))
    runner = AutoTradingRunner(db, get_settings().REDIS_URL)
    return runner.status_for_user(user.id)


@router.post("/auto/run")
async def run_auto_trading_now(
    engine: str | None = Query(default=None),
    db=Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    if engine is not None and engine not in ("scalping", "intraday", "swing"):
        raise HTTPException(status_code=400, detail="engine must be scalping, intraday, or swing")
    runner = AutoTradingRunner(db, get_settings().REDIS_URL)
    config = AutoTradingStore(get_settings().REDIS_URL).get_config(user.id)
    return await runner.run_for_user(user.id, config, engine_filter=engine)


@router.post("", response_model=OrderResponse)
async def place_order(
    payload: OrderCreateRequest,
    db=Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    mode = TradingModeStore(get_settings().REDIS_URL).get(user.id)
    if mode == MODE_PAPER:
        paper = PaperTradeExecutor(db, user.id)
        try:
            return await paper.place_order(payload)
        except OrderRejectedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    executor = OrderExecutor(db, user.id)
    try:
        return await executor.place_order(payload)
    except OrderRejectedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AngelOneAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"{exc}. Switch to paper trading or connect Angel One.",
        ) from exc
    except AngelOneAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("")
async def list_orders(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    executor = OrderExecutor(db, user.id)
    orders = await executor.list_orders()
    return {"orders": orders}


@router.get("/paper/positions")
def paper_positions(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    paper = PaperTradeExecutor(db, user.id)
    return {"positions": paper.list_positions(), "mode": "paper"}


@router.get("/book")
async def order_book(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    mode = TradingModeStore(get_settings().REDIS_URL).get(user.id)
    if mode == MODE_PAPER:
        executor = OrderExecutor(db, user.id)
        orders = await executor.list_orders()
        paper_orders = [o for o in orders if o.get("execution_mode") == "paper"]
        return {"status": True, "source": "paper", "data": paper_orders}

    executor = OrderExecutor(db, user.id)
    try:
        return await executor.sync_order_book()
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/trades")
async def trade_book(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    mode = TradingModeStore(get_settings().REDIS_URL).get(user.id)
    if mode == MODE_PAPER:
        paper = PaperTradeExecutor(db, user.id)
        trades = await paper.list_trades()
        return {"trades": trades, "mode": "paper"}

    executor = OrderExecutor(db, user.id)
    try:
        trades = await executor.trade_book()
        return {"trades": trades, "mode": "live"}
    except AngelOneAuthError as exc:
        paper = PaperTradeExecutor(db, user.id)
        trades = await paper.list_trades()
        if trades:
            return {"trades": trades, "mode": "paper", "note": "Broker not connected; showing paper trades"}
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.patch("/{order_id}")
async def modify_order(
    order_id: str,
    payload: OrderModifyRequest,
    db=Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    if TradingModeStore(get_settings().REDIS_URL).get(user.id) == MODE_PAPER:
        raise HTTPException(status_code=400, detail="Modify is not supported in paper trading mode")

    payload.order_id = order_id
    executor = OrderExecutor(db, user.id)
    try:
        return await executor.modify_order(payload)
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AngelOneAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/{order_id}")
async def cancel_order(
    order_id: str,
    variety: str = "NORMAL",
    db=Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    if TradingModeStore(get_settings().REDIS_URL).get(user.id) == MODE_PAPER:
        raise HTTPException(status_code=400, detail="Cancel is not supported for filled paper orders")

    executor = OrderExecutor(db, user.id)
    try:
        return await executor.cancel_order(OrderCancelRequest(order_id=order_id, variety=variety))
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AngelOneAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


app.include_router(router)


def wait_for_db(retries: int = 20, delay_seconds: int = 2) -> None:
    for attempt in range(1, retries + 1):
        try:
            init_db()
            return
        except Exception:
            if attempt == retries:
                raise
            time.sleep(delay_seconds)


@app.on_event("startup")
def on_startup() -> None:
    wait_for_db()
