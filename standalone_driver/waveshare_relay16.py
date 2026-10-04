"""
------------------------------------------------------------------------------
Name:       waveshare_relay16.py
Purpose:    class allowing control of the Waveshare Modbus POE ETH Relay 16CH
            Using Modbus TCP over Ethernet (standalone, no dependency)

Author:     Yannish

Copyright:  (c) Y.RAMGULAM 2026
Licence:    <your licence>
-------------------------------------------------------------------------------
"""

import socket
import struct
import threading
import logging
from time import sleep

log = logging.getLogger(__name__)

# Network defaults of the board (factory IP is 192.168.1.200, Modbus TCP port 502)
DEFAULT_HOST    = "192.168.1.200"
DEFAULT_PORT    = 502
DEFAULT_UNIT    = 1
DEFAULT_TIMEOUT = 2.0

NUM_RELAYS = 16

# Safe default state, applied by preset(): every relay open.
DEFAULT_STATES = [False] * NUM_RELAYS

#-----------------------------------------------------------------------------------------------------
#
#-----------------------------------------------------------------------------------------------------

# Modbus function codes used by the board
FC_READ_COILS     = 0x01    # relay states (16 bits)
FC_WRITE_COIL     = 0x05    # one relay (FF00 = on, 0000 = off)
FC_WRITE_COILS    = 0x0F    # all 16 relays at once

COIL_ON  = 0xFF00
COIL_OFF = 0x0000

#-----------------------------------------------------------------------------------------------------
#
#-----------------------------------------------------------------------------------------------------

class ModbusError(Exception):
    """
    raised on a Modbus protocol error or a device exception response
    """


class WaveshareRelay16():
    """
    control of Waveshare Modbus POE ETH Relay 16CH using Modbus TCP
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, unit=DEFAULT_UNIT,
                 timeout=DEFAULT_TIMEOUT, channel_names=None):
        """
        Parameters  :
                        host: str
                            IP address of the board
                        port: int
                            Modbus TCP port
                        unit: int
                            Modbus device address
                        timeout: float
                            socket timeout in seconds
                        channel_names: list of str
                            optional alias for each channel (index 0 = CH1), so relays
                            can be addressed by name, eg "DUT_POWER"
        """

        self.host    = host
        self.port    = int(port)
        self.unit    = int(unit)
        self.timeout = timeout

        # channel names, default to the silkscreen labels CH1..CH16
        self.channel_names = [f"CH{i + 1}" for i in range(NUM_RELAYS)]
        if channel_names is not None:
            for i, name in enumerate(channel_names[:NUM_RELAYS]):
                self.channel_names[i] = name

        self._sock = None
        self._tid  = 0
        self._lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    #---------------------------------------------------------------------------
    #   connection / transport
    #---------------------------------------------------------------------------

    def connect(self):
        """
        open the TCP connection (done automatically on the first request)

        Parameters  :   None
        Returns     :   None
        """

        with self._lock:
            self._connect()

    def close(self):
        """
        close the TCP connection

        Parameters  :   None
        Returns     :   None
        """

        with self._lock:
            self._close()

    def _connect(self):
        if self._sock is None:
            log.info("Connecting to relay board %s:%s (unit %s)", self.host, self.port, self.unit)
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._sock.settimeout(self.timeout)

    def _close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("connection closed by device")
            buf += chunk
        return buf

    def _transact(self, pdu):
        """
        send one PDU and return the response PDU. Retries once on a stale socket.

        Parameters  :
                        pdu: bytes
                            function code + data
        Returns     :
                        bytes: response PDU
        """

        with self._lock:
            for attempt in range(2):
                try:
                    self._connect()
                    self._tid = (self._tid + 1) & 0xFFFF
                    mbap = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit)
                    self._sock.sendall(mbap + pdu)
                    tid, _pid, length, _unit = struct.unpack(">HHHB", self._recv_exact(7))
                    resp = self._recv_exact(length - 1)
                    if tid != self._tid:
                        raise ModbusError(f"transaction id mismatch ({tid} != {self._tid})")
                    break
                except (OSError, ConnectionError, ModbusError):
                    self._close()
                    if attempt == 1:
                        raise

        if resp[0] & 0x80:
            raise ModbusError(f"device exception code 0x{resp[1]:02X} for function 0x{resp[0] & 0x7F:02X}")
        if resp[0] != pdu[0]:
            raise ModbusError(f"unexpected function code 0x{resp[0]:02X}")
        return resp

    #---------------------------------------------------------------------------
    #   helpers
    #---------------------------------------------------------------------------

    def _channel_index(self, channel):
        """
        convert a channel (1-based number or name) to a 0-based index

        Parameters  :
                        channel: int or str
                            1..16, or a name from channel_names
        Returns     :
                        int: 0-based index, or None if not supported
        """

        if isinstance(channel, str):
            for i, name in enumerate(self.channel_names):
                if name.lower() == channel.lower():
                    return i
        elif isinstance(channel, int) and 1 <= channel <= NUM_RELAYS:
            return channel - 1

        log.error("Channel: %s not supported. No action performed.", channel)
        return None

    #---------------------------------------------------------------------------
    #   relay API
    #---------------------------------------------------------------------------

    def preset(self):
        """
        Reset the board to its safe default state: all relays OFF.

        Parameters  :   None
        Returns     :   None
        """

        log.info("Presetting relay board: all relays OFF")
        self.set_all(DEFAULT_STATES)

    def set_relay(self, channel, state):
        """
        set one relay

        Parameters  :
                        channel: int or str
                            1..16 (CH1..CH16) or channel name
                        state: int / bool
                            0: open (OFF) | 1: closed (ON)

        Returns     :   None
        """

        idx = self._channel_index(channel)
        if idx is None:
            return
        if state not in [0, 1]:
            log.warning("Relay state: %s not supported. No action performed", state)
            return

        label = self.channel_names[idx]
        if label != f"CH{idx + 1}":
            label = f"{label} (CH{idx + 1})"
        log.info("Setting relay %s to %s", label, "ON" if state else "OFF")
        self._transact(struct.pack(">BHH", FC_WRITE_COIL, idx, COIL_ON if state else COIL_OFF))

    def get_relay(self, channel):
        """
        read one relay state

        Parameters  :
                        channel: int or str
                            1..16 (CH1..CH16) or channel name

        Returns     :
                        bool: True if relay ON, None if channel not supported
        """

        idx = self._channel_index(channel)
        if idx is None:
            return None
        return self.get_states()[idx]

    def get_states(self):
        """
        read all relay states

        Parameters  :   None
        Returns     :
                        list of 16 bool (index 0 = CH1)
        """

        resp = self._transact(struct.pack(">BHH", FC_READ_COILS, 0, NUM_RELAYS))
        bits = int.from_bytes(resp[2:2 + resp[1]], "little")
        return [bool(bits >> i & 1) for i in range(NUM_RELAYS)]

    def set_all(self, states):
        """
        set all 16 relays in a single request

        Parameters  :
                        states: list of 16 int/bool (index 0 = CH1), or a single
                            int/bool applied to every relay

        Returns     :   None
        """

        if isinstance(states, (bool, int)):
            states = [bool(states)] * NUM_RELAYS
        if len(states) != NUM_RELAYS:
            log.error("set_all expects %s states, got %s. No action performed.", NUM_RELAYS, len(states))
            return

        bits = sum(1 << i for i, s in enumerate(states) if s)
        log.info("Setting all relays to 0x%04X", bits)
        self._transact(struct.pack(">BHHB", FC_WRITE_COILS, 0, NUM_RELAYS, 2) + bits.to_bytes(2, "little"))

    def all_on(self):
        """
        close all relays

        Parameters  :   None
        Returns     :   None
        """

        self.set_all(True)

    def all_off(self):
        """
        open all relays

        Parameters  :   None
        Returns     :   None
        """

        self.set_all(False)

    def toggle(self, channel):
        """
        invert one relay

        Parameters  :
                        channel: int or str
                            1..16 (CH1..CH16) or channel name

        Returns     :   None
        """

        state = self.get_relay(channel)
        if state is not None:
            self.set_relay(channel, int(not state))

    def invert_all(self):
        """
        invert every relay

        Parameters  :   None
        Returns     :   None
        """

        self.set_all([not s for s in self.get_states()])

    def pulse(self, channel, duration=0.5, state=1):
        """
        set a relay for a given time then restore the opposite state
        (eg power cycle a DUT with state=0)

        Parameters  :
                        channel: int or str
                            1..16 (CH1..CH16) or channel name
                        duration: float
                            time in seconds
                        state: int
                            state applied during the pulse, 0 or 1

        Returns     :   None
        """

        if self._channel_index(channel) is None:
            return
        self.set_relay(channel, state)
        sleep(duration)
        self.set_relay(channel, 1 - state)

    #
    # END OF CLASS
    #


#-----------------------------------------------------------------------------------------------------
#           UNIT TEST
#-----------------------------------------------------------------------------------------------------

if __name__ == "__main__":

    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # usage: python waveshare_relay16.py [host] [port]   (eg 127.0.0.1 5020 with sim_relay.py)
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT

    with WaveshareRelay16(host=host, port=port) as relay:

        relay.preset()

        for ch in range(1, NUM_RELAYS + 1):
            relay.set_relay(ch, 1)
            sleep(0.1)
        log.info(relay.get_states())

        relay.pulse(1, duration=0.5, state=0)

        relay.all_off()
        log.info(relay.get_states())
