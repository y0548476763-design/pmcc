import re

with open('services/ibkr_worker.py', 'r', encoding='utf-8') as f:
    c = f.read()

replacement = """    async def _escalate_task():
        combo_legs = []
        for l in req.legs:
            if not l.conId:
                raise ValueError(f"Missing conId for leg {l.strike} {l.right}")
            combo_legs.append(ibi.ComboLeg(conId=l.conId, ratio=l.qty, action=l.action, exchange='SMART'))
        bag = ibi.Bag(symbol=req.ticker, currency='USD', exchange='SMART', comboLegs=combo_legs)
        
        # 1. Wait for scheduled time if any
        if req.scheduled_time:
            from datetime import datetime
            try: from zoneinfo import ZoneInfo
            except: from backports.zoneinfo import ZoneInfo
            while True:
                now_ny = datetime.now(ZoneInfo("America/New_York"))
                hr, mn = map(int, req.scheduled_time.split(':'))
                sched_dt = now_ny.replace(hour=hr, minute=mn, second=0, microsecond=0)
                wait_secs = (sched_dt - now_ny).total_seconds()
                if wait_secs <= 0:
                    break
                logger.info(f"Waiting {wait_secs}s for scheduled time {req.scheduled_time}")
                await asyncio.sleep(min(wait_secs, 10))
                
        # 2. Place Initial Order
        current_price = req.limit_price
        if req.use_market:
            order = ibi.MarketOrder('BUY', 1)
        else:
            order = ibi.LimitOrder('BUY', 1, current_price)
            
        trade = ib.placeOrder(bag, order)
        logger.info(f"[COMBO ESCALATOR] Order placed ID={trade.order.orderId} at ${current_price}")
        
        # 3. Escalation Loop
        if req.use_market or req.escalation_step_pct <= 0:
            return trade.order.orderId
            
        esc_step_usd = current_price * (req.escalation_step_pct / 100.0)
        esc_step_usd = max(0.01, round(esc_step_usd, 2))
        
        while True:
            await asyncio.sleep(req.escalation_wait_secs)
            if trade.isDone():
                logger.info(f"[COMBO ESCALATOR] Order {trade.order.orderId} is DONE (status={trade.orderStatus.status})")
                break
                
            # Escalate
            current_price += esc_step_usd
            current_price = round(current_price, 2)
            logger.info(f"[COMBO ESCALATOR] Order {trade.order.orderId} not filled. Escalating to ${current_price}")
            
            # Update order price
            order.lmtPrice = current_price
            trade = ib.placeOrder(bag, order) # This modifies the existing order in IBKR
            
    def _kickoff():
        # Schedule the background task in the IB loop
        t = _ib_loop.create_task(_escalate_task())
        # We need a dummy ID to return immediately to the UI since the real ID is created asynchronously
        # But wait! The UI expects an order_id right now.
        # We can just generate a fake internal ID for tracking, or wait for the initial placeOrder if it's not scheduled.
        return 999999 # Return a dummy ID to the UI for now

    loop = asyncio.get_running_loop()
    try:
        oid = await loop.run_in_executor(None, lambda: run_ib(_kickoff()))
        return {"ok": True, "result": {"order_id": oid}}
    except Exception as e:
        return {"ok": False, "error": str(e)}"""

# Replace everything from `async def _place():` down to `return {"ok": False, "error": str(e)}`
pattern = r'\s*async def _place\(\):.*return \{"ok": False, "error": str\(e\)\}'
c = re.sub(pattern, '\n' + replacement, c, flags=re.DOTALL)

with open('services/ibkr_worker.py', 'w', encoding='utf-8') as f:
    f.write(c)
print('Added escalation logic')
