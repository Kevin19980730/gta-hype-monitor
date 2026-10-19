"""GTA Hype Monitor - weekly Google Trends for GTA VI vs past Rockstar launches.

    py -3.10 app.py            # http://127.0.0.1:8960
The Windows task "GTA Hype Trends Daily" runs daily.py every morning (fetch.py = Google Trends,
preorders.py = Sensor Tower pre-orders + unit-model projection); as a backup, /api/data starts a
background re-pull when trends.json is older than STALE_H hours.

GTA_HOSTED=1 (the public Render copy, published by publish_site.py) serves the published
data read-only: no re-pulls, POSTs get 403, and fetch.py (with its scraper import) isn't loaded.
"""
import datetime as dt
import json
import os
import threading
import time

from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file

BASE = Path(__file__).resolve().parent
JSON = BASE / 'data' / 'trends.json'          # = fetch.OUT_JSON
CSV = BASE / 'data' / 'weekly_stitched.csv'   # = fetch.OUT_CSV
PRE_JSON = BASE / 'data' / 'preorders.json'  # = preorders.OUT_JSON
PRE_CSV = BASE / 'data' / 'sensortower.csv'   # = preorders.OUT_CSV
PORT = int(os.environ.get('PORT', 8960))
HOSTED = os.environ.get('GTA_HOSTED') == '1'
STALE_H = 30
app = Flask(__name__)
state = dict(running=False, error=None, last_try=0.0)
lock = threading.Lock()


def refresh(blocking=False):
    def run():
        errs = []
        for name in ('fetch', 'preorders'):         # each step keeps serving its old output on failure
            try:
                __import__(name).main()
            except Exception as e:
                errs.append(f'{name}: {type(e).__name__}: {e}')
        state['error'] = '; '.join(errs) or None
        state['running'] = False
    with lock:
        if state['running']:
            return False
        state['running'], state['last_try'] = True, time.time()
    if blocking:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
    return True


def load():
    d = json.loads(JSON.read_text(encoding='utf-8'))
    d['preorders'] = json.loads(PRE_JSON.read_text(encoding='utf-8')) if PRE_JSON.exists() else None
    return d


def age_h():
    return (time.time() - os.path.getmtime(JSON)) / 3600 if JSON.exists() else 1e9


@app.before_request
def read_only():
    if HOSTED and request.method != 'GET':
        abort(403)


@app.route('/')
def index():
    html = (BASE / 'templates' / 'index.html').read_text(encoding='utf-8')
    if HOSTED:
        html = html.replace('<body>', '<body class="hosted">', 1)
    return html


@app.route('/healthz')
def healthz():
    return 'ok'


@app.route('/api/data')
def data():
    if HOSTED:
        if not JSON.exists():
            return jsonify(error='no data'), 503
        d = load()
        d['status'] = dict(refreshing=False, error=None, hosted=True)
        return jsonify(d)
    if not JSON.exists():
        refresh(blocking=True)
        if not JSON.exists():
            return jsonify(error=state['error'] or 'no data'), 503
    elif age_h() > STALE_H and time.time() - state['last_try'] > 1800:
        refresh()
    d = load()
    d['status'] = dict(refreshing=state['running'], error=state['error'], age_h=round(age_h(), 1))
    return jsonify(d)


@app.route('/api/refresh', methods=['POST'])
def do_refresh():
    started = refresh(blocking=True)
    return jsonify(ok=state['error'] is None, started=started, error=state['error'])


@app.route('/download.csv')
def download():
    name = dt.date.today().strftime('%Y%m%d') + '_gta_google_trends_weekly.csv'
    return send_file(CSV, as_attachment=True, download_name=name)


@app.route('/preorders.csv')
def download_preorders():
    if not PRE_CSV.exists():
        abort(404)
    name = dt.date.today().strftime('%Y%m%d') + '_gta6_sensortower_preorders.csv'
    return send_file(PRE_CSV, as_attachment=True, download_name=name)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=PORT, debug=False)
