#!/usr/bin/env python
"""
LoadFlow - Flask Load Balancer Simulator
Quick Start Script
"""

import sys
import os
import time
import webbrowser
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    print("\n" + "="*60)
    print("  🚀 LoadFlow - Load Balancer Simulator")
    print("="*60)
    print()
    
    try:
        from app import app
        print("✅ Flask app loaded successfully")
        print()
        
        print("Starting server on http://127.0.0.1:5000...")
        print("-" * 60)
        print()
        print("Press Ctrl+C to stop the server")
        print()
        
        # Open browser after a short delay
        def open_browser():
            time.sleep(2)
            print("\n📱 Opening browser...")
            webbrowser.open('http://127.0.0.1:5000')
        
        import threading
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()
        
        # Run the app
        app.run(
            host='127.0.0.1',
            port=5000,
            debug=False,
            use_reloader=False
        )
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print("\nTroubleshooting:")
        print("1. Make sure Flask is installed: pip install flask")
        print("2. Check that port 5000 is available")
        print("3. See TROUBLESHOOTING.md for more help")
        sys.exit(1)

if __name__ == '__main__':
    main()
