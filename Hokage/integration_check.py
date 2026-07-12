import sys
import os
import time
import subprocess
import requests

def run_check():
    print("=== END-TO-END INTEGRATION CHECK ===")
    
    # 1. Kill any existing port 5000 process first
    print("Clearing port 5000...")
    if os.name == 'nt':
        try:
            subprocess.run(["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", "kill_port_5000.ps1"], check=True)
        except Exception as e:
            print(f"Port clear warning: {e}")
        
    # 2. Start the watchdog in the background
    print("Launching Watchdog supervisor in the background...")
    # Run with Cwd set to the workspace root dynamically
    workspace_root = os.path.dirname(os.path.abspath(__file__))
    watchdog_proc = subprocess.Popen([sys.executable, "watchdog.py"], cwd=workspace_root)
    
    # Wait for the system to boot up (flask needs ~12s as coded in watchdog.py)
    print("Waiting 20 seconds for Hokage and Flask server to boot...")
    time.sleep(20)
    
    success = True
    # 3. Physically ping the endpoints
    endpoints = [
        "/api/v1/health",
        "/api/v1/system/status",
        "/api/v1/watchdog/status"
    ]
    
    for ep in endpoints:
        url = f"http://localhost:5000{ep}"
        try:
            print(f"Pinging {url}...")
            res = requests.get(url, timeout=5)
            print(f"[{res.status_code}] Response: {res.text[:200]}")
            if res.status_code != 200:
                success = False
        except Exception as e:
            print(f"Failed to ping {url}: {e}")
            success = False
            
    # 4. Terminate watchdog and run final port cleanup
    print("Stopping Watchdog supervisor...")
    watchdog_proc.terminate()
    try:
        watchdog_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        watchdog_proc.kill()
        
    print("Final port cleanup...")
    if os.name == 'nt':
        try:
            subprocess.run(["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", "kill_port_5000.ps1"], check=True)
        except Exception as e:
            print(f"Final port clear warning: {e}")
        
    if success:
        print("\n=== INTEGRATION CHECK SUCCESSFUL ===")
        sys.exit(0)
    else:
        print("\n=== INTEGRATION CHECK FAILED ===")
        sys.exit(1)

if __name__ == "__main__":
    run_check()
