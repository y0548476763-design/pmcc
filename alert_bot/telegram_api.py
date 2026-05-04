import requests

def send_telegram_alert(token, chat_id, message):
    """
    Sends a message to the specified Telegram chat.
    """
    if not token or not chat_id:
        return False, "Token or Chat ID is missing."
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True, "Alert sent successfully"
    except Exception as e:
        return False, str(e)
