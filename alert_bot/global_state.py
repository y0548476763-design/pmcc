bot_thread = None
scanner = None
logs = []

def add_log(msg):
    logs.append(msg)
    if len(logs) > 100:
        logs.pop(0)
