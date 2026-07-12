import os
import sys
import time
import subprocess
import requests
import psutil

def send_telegram_alert(message):
    try:
        from dotenv import load_dotenv
        load_dotenv()
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if bot_token and chat_id:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e:
        print(f"Failed to send telegram alert: {e}")

def eradicate_zombies_on_port(port=5000):
    """Scan for and forcefully terminate any existing processes on Port 5000 using psutil."""
    print(f"Aggressively scanning for processes holding port {port}...")
    
    # 1. Inspect processes directly using psutil
    killed_count = 0
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            # Check open connections
            conns = proc.connections(kind='inet')
            for conn in conns:
                if conn.laddr.port == port:
                    pid = proc.info['pid']
                    name = proc.info['name']
                    print(f"Found process '{name}' (PID: {pid}) holding port {port}. Forcefully terminating...")
                    # Terminate process
                    p = psutil.Process(pid)
                    p.terminate()
                    # Wait for termination
                    try:
                        p.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        print(f"Process {pid} failed to terminate. Killing...")
                        p.kill()
                    killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
            
    # 2. Also run the backup PowerShell script kill_port_5000.ps1 if on Windows
    if os.name == 'nt':
        try:
            print("Executing kill_port_5000.ps1 as a secondary cleanup step...")
            subprocess.run(["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", "kill_port_5000.ps1"], check=True)
        except Exception as e:
            print(f"PowerShell cleanup warning: {e}")
            
    if killed_count == 0:
        print(f"No active processes found holding port {port} via direct psutil scanning.")
    else:
        print(f"Eradicated {killed_count} process(es) holding port {port}.")

def monitor():
    print("=========================================")
    print("      Hokage Watchdog Supervisor         ")
    print("=========================================")
    
    # Eradicate any zombies before booting
    eradicate_zombies_on_port(5000)
    
    send_telegram_alert("🔄 *WATCHDOG SUPERVISOR* 🔄\nStarting boot sequence...")
    
    cmd = [sys.executable, "start.py"]
    
    while True:
        print("Booting Hokage system (start.py)...")
        # Start start.py as a subprocess
        proc = subprocess.Popen(cmd)
        
        # Allow time for server and threads to initialize
        time.sleep(12)
        
        fail_count = 0
        while True:
            # Check if subprocess is still running
            if proc.poll() is not None:
                print("Hokage start.py subprocess terminated unexpectedly.")
                break
                
            # Perform health checks
            healthy = True
            try:
                # Ping health endpoint
                res_health = requests.get("http://localhost:5000/api/v1/health", timeout=5)
                if res_health.status_code != 200 or res_health.json().get("status") != "healthy":
                    healthy = False
                    print(f"Health check returned unhealthy: {res_health.text}")
                    
                # Ping watchdog status endpoint to verify autonomous loop health
                res_watchdog = requests.get("http://localhost:5000/api/v1/watchdog/status", timeout=5)
                if res_watchdog.status_code != 200:
                    healthy = False
                    print(f"Watchdog status returned non-200 code: {res_watchdog.status_code}")
                else:
                    watchdog_data = res_watchdog.json()
                    # Check if there are failures/incidents that imply the system has hung
                    # (e.g. system_health score is very low, or some core loops are hung)
                    if watchdog_data.get("system_health", 100) < 50:
                        healthy = False
                        print(f"Watchdog reports critical low system health: {watchdog_data}")
            except Exception as e:
                healthy = False
                print(f"Watchdog connection error: {e}")
                
            if not healthy:
                fail_count += 1
                print(f"Watchdog check failed. Consecutive failures: {fail_count}/3")
            else:
                fail_count = 0
                
            if fail_count >= 3:
                print("Hokage system is unresponsive or degraded. Initiating reboot sequence...")
                send_telegram_alert("🚨 *WATCHDOG ALERT* 🚨\nHokage system is unresponsive or degraded. Initiating auto-restart sequence...")
                break
                
            # Sleep between checks
            time.sleep(10)
            
        # Terminate unresponsive processes
        if proc.poll() is None:
            print("Forcefully stopping start.py process...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("Process failed to exit, killing...")
                proc.kill()
                
        # Clean up port 5000 forcefully before restart
        eradicate_zombies_on_port(5000)
        
        # Cooldown before booting again
        time.sleep(5)

if __name__ == "__main__":
    try:
        monitor()
    except KeyboardInterrupt:
        print("Watchdog supervisor stopped by keyboard interrupt.")
        # Final cleanup
        eradicate_zombies_on_port(5000)
        sys.exit(0)
