"""
K7 LED Controller — ESP32 boot / WiFi setup
Runs on MicroPython (ESP32-C3 Super Mini, XIAO ESP32-S3, etc.).

Network architecture:
  STA → lamp AP  (192.168.4.1, always 12345678) — permanent connection
  AP  → K7-Controller (192.168.5.1) — users browse here

First boot (no config): imports setup.py (portal code) and runs the setup
portal. setup.py is not imported on normal boots, keeping RAM free for server.
"""

import network
import time
import json
import os
import asyncio
from machine import reset

CONFIG_FILE   = 'config.json'
LAMP_PASSWORD = '12345678'
AP_SSID       = 'K7-Controller'
AP_PASSWORD   = '12345678'
AP_IP         = '192.168.5.1'


def _file_exists(path):
    try: os.stat(path); return True
    except OSError: return False


def load_config():
    if _file_exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def connect_sta(ssid, password=LAMP_PASSWORD, timeout=20):
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if sta.isconnected():
        sta.disconnect()
        time.sleep(0.5)
    sta.connect(ssid, password)
    t = 0
    while not sta.isconnected() and t < timeout:
        time.sleep(0.5)
        t += 0.5
        print('.', end='')
    print()
    return sta.isconnected()


def start_ap(ssid=AP_SSID, password=AP_PASSWORD):
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ssid, password=password, authmode=3)
    ap.ifconfig((AP_IP, '255.255.255.0', AP_IP, AP_IP))
    t = 0
    while not ap.active() and t < 5:
        time.sleep(0.2); t += 0.2
    return ap


def boot():
    cfg = load_config()

    # Support old config format (suffix + device) and new (lamp_ssid + device)
    if not cfg.get('lamp_ssid') and cfg.get('suffix'):
        prefix = 'K7_Pro' if cfg.get('device') == 'k7pro' else 'K7mini'
        cfg['lamp_ssid'] = prefix + cfg['suffix']

    if not cfg.get('lamp_ssid'):
        print('No config — starting setup portal')
        import setup
        setup.run_portal()
        return

    lamp_ssid = cfg['lamp_ssid']
    device    = cfg.get('device', 'k7mini')

    print(f'Connecting STA → {lamp_ssid} ...', end='')
    if not connect_sta(lamp_ssid):
        print('Failed to connect to lamp AP — falling back to setup portal')
        import setup
        setup.run_portal()
        return

    ap = start_ap()
    print(f'AP ready: {AP_SSID}  @  {ap.ifconfig()[0]}')
    print('Browse to http://192.168.5.1')

    import gc; gc.collect()
    try:
        import server as srv
        srv.cfg['device'] = device
        asyncio.run(srv.main())
    except Exception as e:
        import sys
        with open('boot_error.txt', 'w') as f:
            f.write(str(e) + '\n')
            sys.print_exception(e, f)
        raise


if __name__ == '__main__':
    boot()
