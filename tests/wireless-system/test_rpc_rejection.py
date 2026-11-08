"""Retain HTTP rejection status without credentials or replaying a request."""
from pathlib import Path
import sys
import json
import unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/adapter'))
from mklink_remote.s3_rpc import Endpoint

class RejectionTests(unittest.TestCase):
    def test_status_is_retained_and_post_not_repeated(self):
        for code in (400,401,408,429,503):
            with self.subTest(code=code):
                conn=MagicMock();conn.getresponse.return_value.__enter__.return_value.status=code
                ep=Endpoint({'transport':'http','address':'http://fixture.invalid','token':'secret-test-token'})
                with patch('http.client.HTTPConnection',return_value=conn):
                    with self.assertRaises(ConnectionError) as error:ep.rpc('probe.stream.write',{'secret':'not-for-log'})
                self.assertIn(f'HTTP {code}',str(error.exception))
                self.assertNotIn('secret',str(error.exception))
                conn.request.assert_called_once();conn.close.assert_called_once()
                self.assertIsNone(ep.http)

    def test_only_proven_not_executed_408_is_retried_once(self):
        for marked in (True,False):
            a=MagicMock();b=MagicMock()
            first=a.getresponse.return_value.__enter__.return_value
            first.status=408;first.getheader.return_value='no' if marked else None
            second=b.getresponse.return_value.__enter__.return_value
            second.status=200;second.length=None
            second.read.side_effect=lambda limit:json.dumps(dict(v=1,id=json.loads(b.request.call_args.args[2])['id'],ok=True,data={})).encode()
            ep=Endpoint({'transport':'http','address':'http://fixture.invalid','token':'test'})
            with patch('http.client.HTTPConnection',side_effect=[a,b]):
                if marked:self.assertEqual(ep.rpc('probe.stream.write',{}),{})
                else:
                    with self.assertRaises(ConnectionError):ep.rpc('probe.stream.write',{})
            self.assertEqual(a.request.call_count,1)
            self.assertEqual(b.request.call_count,int(marked))
            if marked:self.assertEqual(a.request.call_args,b.request.call_args)
    def test_proven_rejection_is_bounded_and_network_failure_never_replayed(self):
        for kind in ('twice','lost'):
            a=MagicMock();b=MagicMock()
            for c in (a,b):
                r=c.getresponse.return_value.__enter__.return_value;r.status=408;r.getheader.return_value='no'
            if kind=='lost':a.getresponse.side_effect=ConnectionResetError()
            ep=Endpoint({'transport':'http','address':'http://fixture.invalid','token':'test'})
            with patch('http.client.HTTPConnection',side_effect=[a,b]) as factory:
                with self.assertRaises(ConnectionError):ep.rpc('probe.stream.write',{})
                self.assertEqual(factory.call_count,2 if kind=='twice' else 1)
            self.assertIsNone(ep.http)

if __name__=='__main__':unittest.main()
