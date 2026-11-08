"""Run with PYTHONPATH pointing to the staged Remote server."""
import binascii
import struct
import unittest

from mklink.dump_memory import DumpMemoryParser, MAGIC
from mklink.legacy_dump import command_for as build_dump_mem_command


class EchoTest(unittest.TestCase):
    def test_only_startup_echo_is_excluded(self):
        command = build_dump_mem_command([(0x20018BE0, 2048)], .1)
        echo = command.encode() + b'\n\r\n>>> '
        self.assertEqual(len(echo), 45)
        payload = bytes(2048)
        size = 19 + 3 + len(payload) + 6
        body = MAGIC + struct.pack('<QHBBH', 1, size, 1, 0, len(payload)) + payload + b'\0\0'
        frame = body + struct.pack('<I', binascii.crc32(body) & 0xFFFFFFFF)
        for split in range(len(echo) + 1):
            parser = DumpMemoryParser([2048], startup_command=command)
            self.assertEqual(parser.feed(echo[:split]), [])
            self.assertEqual(parser.feed(echo[split:] + frame)[0]['regions'], [(0, payload)])
            self.assertEqual(parser.dropped_bytes, 0)
            parser.feed(echo + frame)
            self.assertEqual(parser.dropped_bytes, 45)
        parser = DumpMemoryParser([2048], startup_command=command)
        self.assertEqual(len(parser.feed(b'?' + echo + frame)), 1)
        self.assertEqual(parser.dropped_bytes, 46)
        parser.feed(frame[:-1] + bytes([frame[-1] ^ 1]))
        self.assertEqual(parser.crc_errors, 1)


if __name__ == '__main__':
    unittest.main()
