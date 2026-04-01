#!/usr/bin/env python
"""
LoadFlow Debug Mode
Run this if you're having connection issues
"""

import sys
import socket
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_port_available(host, port):
    """Check if a port is available"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        result = sock.connect_ex((host, port))
        return result != 0  # 0 means port is in use
    finally:
        sock.close()

def main():
    print("\n" + "="*70)
    print("  LoadFlow - Debug Mode")
    print("="*70 + "\n")
    
    # Pre-flight checks
    print("🔍 Running pre-flight checks...\n")
    
    # Check Python version
    print(f"✅ Python {sys.version.split()[0]}")
    
    # Check Flask
    try:
        import flask
        print(f"✅ Flask installed")
    except:
        print("❌ Flask not installed! Run: pip install flask")
        sys.exit(1)
    
    # Check port
    if check_port_available('127.0.0.1', 5000):
        print("✅ Port 5000 available")
    else:
        print("❌ Port 5000 in use!")
        print("   Kill existing process and try again")
        sys.exit(1)
    
    # Load app
    print("✅ Loading Flask app...")
    try:
        from app import app
    except Exception as e:
        print(f"❌ Failed to load app: {e}")
        sys.exit(1)
    
    print("\n" + "="*70)
    print("  Starting server on http://127.0.0.1:5000")
    print("  Press Ctrl+C to stop")
    print("="*70 + "\n")
    
    try:
        # Run with verbose logging
        app.run(
            host='127.0.0.1',
            port=5000,
            debug=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\n\nServer stopped.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
