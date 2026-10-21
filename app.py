#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""Flask web UI for the Waveshare Modbus POE ETH Relay 16CH.

Run:  python app.py   (opens http://127.0.0.1:5000 in the browser; add --no-browser to skip)
"""
import json
import os
import re
import sys
import threading
import webbrowser

from flask import Flask, jsonify, request, send_from_directory

from relay_client import NUM_RELAYS, RelayClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

DEFAULT_CONFIG = {
    'host': '192.168.1.200',
    'port': 4196,
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


def map_keys():
    """Config keys "map1", "map2", ... in numeric order."""
    keys = [k for k in config if re.fullmatch(r'map\d+', k) and isinstance(config[k], list)]
    return sorted(keys, key=lambda k: int(k[3:]))


def resolve_channel(ref):
    """A map entry is "CHn" / n (channel number) or a channel name. Returns 1-based channel or None."""
    m = re.fullmatch(r'(?i)ch(\d+)', str(ref).strip())
    if isinstance(ref, int) or m:
        ch = int(m.group(1)) if m else ref
        return ch if 1 <= ch <= NUM_RELAYS else None
    if ref in config['names']:
        return config['names'].index(ref) + 1
    return None


def resolve_map(key):
    channels = {resolve_channel(r) for r in config[key]}
    return sorted(c for c in channels if c)


def config_response():
    maps = [{'name': k, 'channels': resolve_map(k)} for k in map_keys()]
    return dict(config, maps=maps)


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
    return jsonify(config_response())


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
    return jsonify(ok=True, config=config_response())


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


@app.post('/api/map/<name>')
def apply_map(name):
    """Turn ON the relays listed in config[name], all others OFF (one 0x0F write)."""
    if name not in map_keys():
        return jsonify(ok=False, error='unknown map "%s"' % name), 404
    channels = resolve_map(name)
    return run_and_read(lambda: relay.set_all([ch in channels for ch in range(1, NUM_RELAYS + 1)]))


@app.post('/api/all/invert')
def all_invert():
    return run_and_read(relay.invert_all)


if __name__ == '__main__':
    # open the UI in the default browser once the server is up (skip with --no-browser)
    if '--no-browser' not in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=('http://127.0.0.1:5000',)).start()
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
