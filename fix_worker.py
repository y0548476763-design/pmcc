import re

with open('services/ibkr_worker.py', 'r', encoding='utf-8') as f:
    c = f.read()

models = """class ComboLeg(BaseModel):
    strike: float
    expiry: str
    right: str
    action: str  # BUY or SELL
    qty: int = 1
    conId: Optional[int] = None

class PlaceComboRequest(BaseModel):
    ticker: str
    legs: List[ComboLeg]
    limit_price: float
    use_market: bool = False
    escalation_step_pct: float = 1.0
    escalation_wait_secs: int = 180
    scheduled_time: Optional[str] = None"""

c = re.sub(r'class ComboLeg\(BaseModel\):.*?qty: int = 1', models, c, flags=re.DOTALL)

endpoint = """@app.post("/order/combo")
async def order_combo(req: PlaceComboRequest):
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
        
    def _place():
        combo_legs = []
        for l in req.legs:
            if not l.conId:
                raise ValueError(f"Missing conId for leg {l.strike} {l.right}")
            combo_legs.append(ibi.ComboLeg(conId=l.conId, ratio=l.qty, action=l.action, exchange='SMART'))
        bag = ibi.Bag(symbol=req.ticker, currency='USD', exchange='SMART', comboLegs=combo_legs)
        if req.use_market:
            order = ibi.MarketOrder('BUY', 1)
        else:
            order = ibi.LimitOrder('BUY', 1, req.limit_price)
            
        trade = ib.placeOrder(bag, order)
        return trade.order.orderId

    loop = asyncio.get_running_loop()
    try:
        oid = await loop.run_in_executor(None, lambda: run_ib(_place()))
        return {"ok": True, "result": {"order_id": oid}}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/ibkr/place_order")"""

c = c.replace('@app.post("/api/ibkr/place_order")', endpoint)

with open('services/ibkr_worker.py', 'w', encoding='utf-8') as f:
    f.write(c)
print('Fixed ibkr_worker.py')
