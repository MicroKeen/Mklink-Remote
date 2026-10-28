"""Keep Windows serial timeout changes separate from line configuration.

pySerial's Windows backend reissues SetCommState for every timeout assignment.
esptool changes/restores timeouts for every command. On this machine a captured
stack showed long stalls in that redundant SetCommState path. This process-local
adapter retains pySerial's line/flow-control implementation and updates only
COMMTIMEOUTS when line settings are unchanged. No installed library is modified.
"""
import os
import serial

if os.name == 'nt':
    import ctypes
    from serial import win32
    from serial.serialwin32 import Serial as WindowsSerial

    class Serial(WindowsSerial):
        def open(self):
            self._configured_line = None
            self._configured_timeouts = None
            return super().open()

        def _line_settings(self):
            rs485 = self._rs485_mode
            rs485_key = None if rs485 is None else (
                rs485.rts_level_for_tx, rs485.rts_level_for_rx,
                rs485.delay_before_tx, rs485.delay_before_rx, rs485.loopback)
            # RTS/DTR state changes already use EscapeCommFunction directly.
            # Flow-control changes still require the full DCB implementation.
            return (self._baudrate, self._bytesize, self._parity, self._stopbits,
                    self._rtscts, self._dsrdtr, self._xonxoff, rs485_key)

        def _reconfigure_port(self):
            if not self._port_handle:
                raise serial.SerialException('Can only operate on a valid port handle')
            line = self._line_settings()
            timeout_key = (self._timeout, self._inter_byte_timeout, self._write_timeout)
            if getattr(self, '_configured_line', None) != line:
                super()._reconfigure_port()
                self._configured_line = line
                self._configured_timeouts = timeout_key
                return
            if getattr(self, '_configured_timeouts', None) == timeout_key:
                return
            # COMMTIMEOUTS mapping follows pySerial 3.x serialwin32 (BSD-3-Clause,
            # Chris Liechti). Do not issue Get/SetCommState or touch control lines.
            values = win32.COMMTIMEOUTS()
            if self._timeout == 0:
                values.ReadIntervalTimeout = win32.MAXDWORD
            elif self._timeout is not None:
                values.ReadTotalTimeoutConstant = max(int(self._timeout * 1000), 1)
            if self._timeout != 0 and self._inter_byte_timeout is not None:
                values.ReadIntervalTimeout = max(int(self._inter_byte_timeout * 1000), 1)
            if self._write_timeout == 0:
                values.WriteTotalTimeoutConstant = win32.MAXDWORD
            elif self._write_timeout is not None:
                values.WriteTotalTimeoutConstant = max(int(self._write_timeout * 1000), 1)
            if not win32.SetCommTimeouts(self._port_handle, ctypes.byref(values)):
                raise serial.SerialException('Cannot update serial timeouts: {!r}'.format(ctypes.WinError()))
            self._configured_timeouts = timeout_key
else:
    Serial = serial.Serial


def install_for_esptool():
    """serial_for_url resolves this class in this worker process only."""
    if os.name == 'nt':
        serial.Serial = Serial
        return True
    return False
