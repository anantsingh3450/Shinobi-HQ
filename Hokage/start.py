import os
import sys
is_testing = "pytest" in sys.modules or any("pytest" in arg for arg in sys.argv)
if not is_testing:
    from dotenv import load_dotenv
    load_dotenv(r"C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage\.env")

from hokage.boot import main

if __name__ == "__main__":
    main()
