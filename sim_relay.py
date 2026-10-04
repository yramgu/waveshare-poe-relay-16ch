#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""Tiny Modbus TCP simulator of the 16CH relay board, for testing without hardware.

Run:  python sim_relay.py [port]      (default 5020)
This speaks Modbus TCP only (it replaces the relay board, not the web page).
In a second terminal run  python app.py, open http://127.0.0.1:5000,
then set IP 127.0.0.1 / port 5020 in the top bar and click Connect.
"""
import socket
import struct
import sys
import threading

coils = [False] * 16
lock = threading.Lock()


def handle_pdu(pdu):
    fc = pdu[0]
    with lock:
        if fc == 0x01:
            addr, qty = struct.unpack('>HH', pdu[1:5])
            bits = sum(1 << i for i in range(qty) if coils[addr + i])
            nbytes = (qty + 7) // 8
            return bytes([fc, nbytes]) + bits.to_bytes(nbytes, 'little')
        if fc == 0x05:
            addr, val = struct.unpack('>HH', pdu[1:5])
            if addr == 0x00FF:                       # all relays
                for i in range(16):
                    coils[i] = (not coils[i]) if val == 0x5500 else val == 0xFF00
            elif addr < 16:
                coils[addr] = (not coils[addr]) if val == 0x5500 else val == 0xFF00
            else:
                return bytes([fc | 0x80, 0x02])
            return pdu[:5]
        if fc == 0x0F:
            addr, qty, nbytes = struct.unpack('>HHB', pdu[1:6])
            bits = int.from_bytes(pdu[6:6 + nbytes], 'little')
            for i in range(qty):
                coils[addr + i] = bool(bits >> i & 1)
            return pdu[:5]
    return bytes([fc | 0x80, 0x01])


def serve_client(conn, addr):
    print('client', addr)
    with conn:
        try:
            while True:
                hdr = conn.recv(7)
                if len(hdr) < 7:
                    break
                if hdr[:4] in (b'GET ', b'HEAD', b'POST'):   # someone opened this port in a browser
                    msg = (b'This is the Modbus relay simulator, not the web UI.\n'
                           b'Run "python app.py" and open http://127.0.0.1:5000,\n'
                           b'then connect to IP 127.0.0.1, port 5020.\n')
                    conn.sendall(b'HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n'
                                 % len(msg) + msg)
                    break
                tid, pid, length, unit = struct.unpack('>HHHB', hdr)
                pdu = conn.recv(length - 1)
                resp = handle_pdu(pdu)
                conn.sendall(struct.pack('>HHHB', tid, 0, len(resp) + 1, unit) + resp)
                print('fc=0x%02X -> %s' % (pdu[0], ''.join('1' if c else '0' for c in coils)))
        except OSError:
            pass
    print('client gone', addr)


def main(port=5020):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen()
    print('Relay simulator (Modbus TCP) on 127.0.0.1:%d' % port)
    print('Web UI: run "python app.py", open http://127.0.0.1:5000, connect to 127.0.0.1 port %d' % port)
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=serve_client, args=(conn, addr), daemon=True).start()


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5020)
