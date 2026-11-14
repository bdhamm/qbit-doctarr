import os
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, Response
from .database import init_db
from .core.migrations import run_migrations
from .scheduler import start_scheduler

def setup_logging():
    """Configure the root logger based on the config file."""
    log_to_file = False
    level_str = "INFO"
    
    try:
        with open("/config/config.json", "r") as f:
            config = json.load(f)
        level_str = config.get("log_level", "INFO").upper()
        log_to_file = config.get("log_to_file", False)
    except Exception:
        pass

    level = getattr(logging, level_str, logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # Remove existing handlers to prevent duplicate logs
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    
    # Always log to stdout (Docker logs)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    
    # Optionally log to file (5MB limit, 2 backups)
    if log_to_file:
        try:
            fh = RotatingFileHandler("/config/qbit-doctarr.log", maxBytes=5*1024*1024, backupCount=2)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception as e:
            logger.error(f"Failed to set up file logging: {e}")

def create_app():
    # Initialize logging FIRST
    setup_logging()
    
    app = Flask(__name__)
    
    # Ensure config dir exists
    os.makedirs("/config", exist_ok=True)
    
    # Initialize Database
    init_db()
    
    # Apply pending config migrations BEFORE scheduler reads config.
    run_migrations()
    
    @app.before_request
    def require_basic_auth():
        # Use the dynamic config loader from routes so it respects updates without restart
        from .routes._shared import load_config
        config = load_config()
        sec = config.get("security", {})
        
        if not sec.get("basic_auth_enabled", False):
            return
            
        auth = request.authorization
        if not auth or auth.username != sec.get("basic_auth_username", "admin") or auth.password != sec.get("basic_auth_password", ""):
            return Response(
                'Could not verify your access level for that URL.\n'
                'You have to login with proper credentials', 401,
                {'WWW-Authenticate': 'Basic realm="Login Required"'}
            )

    # Start Background Scheduler (unless we are running Flask's auto-reloader)
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        start_scheduler()
    
    # Register routes
    from .routes import bp
    app.register_blueprint(bp)
    
    return app
