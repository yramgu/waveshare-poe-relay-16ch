#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""Modbus TCP client for the Waveshare Modbus POE ETH Relay 16CH.

Frame = MBAP header (transaction id, protocol id=0, length, unit id) + PDU.
Used function codes:
    0x01 read coils           -> relay states (16 bits)
    0x05 write single coil    -> one relay (FF00 = on, 0000 = off)
    0x0F write multiple coils -> all 16 relays at once
"""
import socket
import struct
import threading

NUM_RELAYS = 16


class ModbusError(Exception):
    pass


class RelayClient:
    def __init__(self, host='192.168.1.200', port=502, unit=1, timeout=2.0):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self._sock = None
        self._tid = 0
        self._lock = threading.Lock()

    # ---- connection -------------------------------------------------------
    def configure(self, host, port, unit):
        with self._lock:
            self._close()
            self.host, self.port, self.unit = host, int(port), int(unit)

    def _connect(self):
        if self._sock is None:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._sock.settimeout(self.timeout)

    def _close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self):
        with self._lock:
            self._close()

    def _recv_exact(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError('connection closed by device')
            buf += chunk
        return buf

    def _transact(self, pdu):
        """Send one PDU, return the response PDU. Retries once on a stale socket."""
        with self._lock:
            for attempt in range(2):
                try:
                    self._connect()
                    self._tid = (self._tid + 1) & 0xFFFF
                    mbap = struct.pack('>HHHB', self._tid, 0, len(pdu) + 1, self.unit)
                    self._sock.sendall(mbap + pdu)
                    tid, pid, length, _unit = struct.unpack('>HHHB', self._recv_exact(7))
                    resp = self._recv_exact(length - 1)
                    if tid != self._tid:
                        raise ModbusError('transaction id mismatch (%d != %d)' % (tid, self._tid))
                    break
                except (OSError, ConnectionError, ModbusError):
                    self._close()
                    if attempt == 1:
                        raise
        if resp[0] & 0x80:
            raise ModbusError('device exception code 0x%02X for function 0x%02X'
                              % (resp[1], resp[0] & 0x7F))
        if resp[0] != pdu[0]:
            raise ModbusError('unexpected function code 0x%02X' % resp[0])
        return resp

    # ---- relay API --------------------------------------------------------
    def read_states(self):
        """Return a list of 16 bools (index 0 = CH1)."""
        resp = self._transact(struct.pack('>BHH', 0x01, 0, NUM_RELAYS))
        bits = int.from_bytes(resp[2:2 + resp[1]], 'little')
        return [bool(bits >> i & 1) for i in range(NUM_RELAYS)]

    def set_relay(self, index, on):
        """index is 0-based (0 = CH1)."""
        if not 0 <= index < NUM_RELAYS:
            raise ValueError('relay index out of range')
        self._transact(struct.pack('>BHH', 0x05, index, 0xFF00 if on else 0x0000))

    def set_all(self, states):
        """states: list of 16 bools, written in one 0x0F request."""
        bits = sum(1 << i for i, s in enumerate(states) if s)
        self._transact(struct.pack('>BHHB', 0x0F, 0, NUM_RELAYS, 2) + bits.to_bytes(2, 'little'))

    def invert_all(self):
        self.set_all([not s for s in self.read_states()])
