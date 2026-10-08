"""Start the development server:  python run.py"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug/reloader stay OFF: the reloader would start a second process, and with
    # background workers that could process the same job twice.
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            debug=False, threaded=True)
