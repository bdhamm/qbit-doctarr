"""HTML page routes. Eight GET endpoints, all return rendered templates."""

from flask import render_template

from ._shared import load_config
from . import bp


@bp.route('/')
def dashboard(): return render_template('dashboard.html')

@bp.route('/stalled')
def stalled(): return render_template('stalled.html')

@bp.route('/missing')
def missing(): return render_template('missing.html')

@bp.route('/history')
def history(): return render_template('history.html')

@bp.route('/trends')
def trends(): return render_template('trends.html')

@bp.route('/maintenance')
def maintenance(): return render_template('maintenance.html')

@bp.route('/settings')
def settings():
    config = load_config()
    return render_template('settings.html', config=config)

@bp.route('/help')
def help_page(): return render_template('help.html')
