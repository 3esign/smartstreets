"""SmartStreet launcher — starts the API + dashboard on http://localhost:8000

Usage:
    python run.py
Then open http://localhost:8000 in your browser.
"""

import webbrowser
import threading

import uvicorn


def _open_browser():
    webbrowser.open("http://localhost:8000")


if __name__ == "__main__":
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=False)
