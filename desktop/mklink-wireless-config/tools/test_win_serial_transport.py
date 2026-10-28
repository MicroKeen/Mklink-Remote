import os
import unittest
from unittest.mock import patch
import serial
from win_serial_transport import Serial


@unittest.skipUnless(os.name == 'nt', 'Windows API boundary tests')
class WindowsSerialTests(unittest.TestCase):
    def setUp(self):
        from serial import win32
        self.win32 = win32
        self.events = []
        self.handles = iter(range(100, 200))
        def timeouts(handle, pointer):
            v = getattr(pointer,'_obj',pointer)
            self.events.append(('timeout', v.ReadIntervalTimeout,
                                v.ReadTotalTimeoutConstant, v.WriteTotalTimeoutConstant))
            return 1
        def state(handle, pointer):
            v = pointer._obj
            self.events.append(('line', v.BaudRate, v.ByteSize, v.Parity,
                                v.StopBits, v.fRtsControl, v.fDtrControl))
            return 1
        def escape(handle, command):self.events.append(('escape', command));return 1
        self.mocks = patch.multiple(win32,
            CreateFile=lambda *a:next(self.handles), CreateEvent=lambda *a:next(self.handles),
            SetupComm=lambda *a:1, GetCommTimeouts=lambda *a:1, PurgeComm=lambda *a:1,
            CloseHandle=lambda *a:1, GetOverlappedResult=lambda *a:1,
            GetCommState=lambda *a:1, SetCommState=state, SetCommTimeouts=timeouts,
            SetCommMask=lambda *a:1, EscapeCommFunction=escape)
        self.mocks.start()
        self.port = Serial(port=None, timeout=3, write_timeout=5)
        self.port.port = 'COM99';self.port.dtr=False;self.port.rts=False;self.port.open()

    def tearDown(self):
        try:self.port.close()
        finally:self.mocks.stop()

    def lines(self):return [e for e in self.events if e[0]=='line']

    def test_command_timeout_changes_do_not_reconfigure_uart(self):
        first=len(self.lines())
        for value in [3, 3, .1, 3, 0, None, 3]:self.port.timeout=value
        self.assertEqual(len(self.lines()),first)
        self.assertIn(('timeout',self.win32.MAXDWORD,0,5000),self.events)
        self.assertIn(('timeout',0,100,5000),self.events)
        self.assertIn(('timeout',0,0,5000),self.events)
        count=len(self.events);self.port.timeout=3
        self.assertEqual(len(self.events),count)

    def test_baud_and_uart_format_changes_are_sent(self):
        self.port.baudrate=460800
        self.assertEqual(self.lines()[-1][1],460800)
        self.port.bytesize=serial.SEVENBITS;self.port.parity=serial.PARITY_EVEN
        self.port.stopbits=serial.STOPBITS_TWO
        self.assertEqual(self.lines()[-1][2:5],(7,self.win32.EVENPARITY,self.win32.TWOSTOPBITS))
        count=len(self.lines());self.port.timeout=.2
        self.assertEqual(len(self.lines()),count)

    def test_explicit_reset_lines_are_preserved_without_timeout_side_effects(self):
        self.port.rts=True;self.port.dtr=True
        self.assertIn(('escape',self.win32.SETRTS),self.events)
        self.assertIn(('escape',self.win32.SETDTR),self.events)
        count=len(self.lines());self.port.timeout=.4
        self.assertEqual(len(self.lines()),count)
        self.port.rtscts=True;self.port.dsrdtr=True
        self.assertEqual(self.lines()[-1][-2:],(self.win32.RTS_CONTROL_HANDSHAKE,self.win32.DTR_CONTROL_HANDSHAKE))

    def test_reopen_configures_new_handle_even_with_identical_settings(self):
        previous=len(self.lines());self.port.close();self.port.open()
        self.assertEqual(len(self.lines()),previous+1)

    def test_failed_timeout_update_is_reported_and_not_cached(self):
        with patch.object(self.win32,'SetCommTimeouts',return_value=0):
            with self.assertRaises(serial.SerialException):self.port.timeout=.7
        previous=len(self.events);self.port.timeout=.7
        self.assertEqual(len(self.events),previous+1)


if __name__=='__main__':unittest.main()
