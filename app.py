"""Start the local release-assessment dashboard: python app.py"""
import sys

from backend.main import main

if __name__ == '__main__':
    # Never crash on log text the console code page cannot encode.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace')
    main()
