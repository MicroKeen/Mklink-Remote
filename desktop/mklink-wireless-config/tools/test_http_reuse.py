import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapter'))
from mklink_remote.s3_rpc import Endpoint


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.calls.append((self.client_address, req['method']))
        if req['method'] == 'lost_reply':
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
            return
        if req['method'] == 'redirect':
            self.send_response(307)
            self.send_header('Location', '/other')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        body = json.dumps(dict(v=1, id=req['id'], ok=True, data={'value': 1})).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        if req['method'] == 'close':
            self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)


class HttpReuseTest(unittest.TestCase):
    def test_reuse_server_close_and_no_replay(self):
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            server.calls = []
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            ep = Endpoint(dict(address=f'http://127.0.0.1:{server.server_port}', token='test'))
            try:
                for name in ('read', 'close', 'read'):
                    self.assertEqual(ep.rpc(name, {}), {'value': 1})
                self.assertEqual(server.calls[0][0], server.calls[1][0])
                self.assertNotEqual(server.calls[1][0], server.calls[2][0])
                for method in ('lost_reply', 'redirect'):
                    with self.assertRaisesRegex(ConnectionError, 'no replay'):
                        ep.rpc(method, {})
                self.assertEqual([r[1] for r in server.calls],
                                 ['read', 'close', 'read', 'lost_reply', 'redirect'])
            finally:
                ep.close()
                server.shutdown()
                thread.join()


if __name__ == '__main__':
    unittest.main()
