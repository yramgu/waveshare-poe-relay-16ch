#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""Flask web UI for the Waveshare Modbus POE ETH Relay 16CH.

Run:  python app.py   (opens http://127.0.0.1:5000 in the browser; add --no-browser to skip)
"""
import json
import os
import sys
import threading
import webbrowser

from flask import Flask, jsonify, request, send_from_directory

from relay_client import NUM_RELAYS, RelayClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

DEFAULT_CONFIG = {
    'host': '192.168.1.200',
    'port': 502,
    'unit': 1,
    'names': ['CH%d' % (i + 1) for i in range(NUM_RELAYS)],
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg.update(json.load(f))
    names = list(cfg['names'])[:NUM_RELAYS]
    cfg['names'] = names + DEFAULT_CONFIG['names'][len(names):]
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


config = load_config()
relay = RelayClient(config['host'], config['port'], config['unit'])
app = Flask(__name__, static_folder='static', static_url_path='/static')


def state_response():
    try:
        return jsonify(ok=True, states=relay.read_states())
    except Exception as e:  # network / modbus errors go back to the UI
        return jsonify(ok=False, error=str(e)), 502


def run_and_read(action):
    try:
        action()
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 502
    return state_response()


@app.route('/')
def index():
    return send_from_directory(os.path.join(BASE_DIR, 'static'), 'index.html')


@app.route('/ui/<path:filename>')
def ui_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'ui'), filename)


@app.get('/api/config')
def get_config():
    return jsonify(config)


@app.post('/api/config')
def set_config():
    data = request.get_json(force=True)
    if 'host' in data or 'port' in data or 'unit' in data:
        try:
            port, unit = int(data.get('port', config['port'])), int(data.get('unit', config['unit']))
        except (TypeError, ValueError):
            return jsonify(ok=False, error='port and unit must be integers'), 400
        config.update(host=str(data.get('host', config['host'])).strip(), port=port, unit=unit)
        relay.configure(config['host'], config['port'], config['unit'])
    if 'names' in data:
        names = [str(n).strip()[:24] or 'CH%d' % (i + 1) for i, n in enumerate(data['names'][:NUM_RELAYS])]
        config['names'] = names + DEFAULT_CONFIG['names'][len(names):]
    save_config(config)
    return jsonify(ok=True, config=config)


@app.get('/api/state')
def get_state():
    return state_response()


@app.post('/api/relay/<int:channel>')
def set_relay(channel):
    """channel is 1-based (CH1..CH16). Body: {"on": true|false}"""
    if not 1 <= channel <= NUM_RELAYS:
        return jsonify(ok=False, error='channel must be 1..%d' % NUM_RELAYS), 400
    on = bool(request.get_json(force=True).get('on'))
    return run_and_read(lambda: relay.set_relay(channel - 1, on))


@app.post('/api/all/on')
def all_on():
    return run_and_read(lambda: relay.set_all([True] * NUM_RELAYS))


@app.post('/api/all/off')
def all_off():
    return run_and_read(lambda: relay.set_all([False] * NUM_RELAYS))


@app.post('/api/all/invert')
def all_invert():
    return run_and_read(relay.invert_all)


if __name__ == '__main__':
    # open the UI in the default browser once the server is up (skip with --no-browser)
    if '--no-browser' not in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=('http://127.0.0.1:5000',)).start()
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
