import sys
import json
import os
from scanner import AlertScanner

CONFIG_FILE = "settings.json"

def main():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Configuration file '{CONFIG_FILE}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    except Exception as e:
        print(f"Error parsing '{CONFIG_FILE}': {e}", file=sys.stderr)
        sys.exit(1)

    # Initialize the scanner
    print("Initializing AlertScanner...")
    scanner = AlertScanner(config, log_callback=print)

    # Run exactly one scan cycle
    print("Starting Headless Scan Cycle...")
    try:
        scanner.scan_once()
        print("Scan Cycle Completed Successfully.")
        sys.exit(0)
    except Exception as e:
        print(f"Critical error during scan: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
