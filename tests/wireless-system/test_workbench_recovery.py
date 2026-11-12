"""Offline session/credential boundary tests; no serial, BLE or target calls."""
from pathlib import Path
import io
import json
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'desktop/mklink-wireless-config/adapter'))
from mklink_remote.s3_workbench import Workbench, main

NODE = dict(node_id='020000123456', transport='http', address='http://fixture.invalid', token='a' * 32)


class WorkbenchRecoveryTests(unittest.TestCase):
    def test_control_frames_survive_windows_legacy_stdout_encoding(self):
        for response in ({'message': '恢复完成：设备'}, ValueError('恢复失败：设备')):
            with self.subTest(response=response):
                raw = io.BytesIO()
                output = io.TextIOWrapper(raw, encoding='gbk')
                frame = {'id': 1, 'params': {'project_root': 'D:/目标工程'}}
                input_stream = io.TextIOWrapper(io.BytesIO((json.dumps(frame, ensure_ascii=False) + '\n').encode('utf8')), encoding='gbk')
                worker = Mock()
                if isinstance(response, Exception):
                    worker.dispatch.side_effect = response
                else:
                    worker.dispatch.return_value = response
                with patch('mklink_remote.s3_workbench.Workbench', return_value=worker), \
                     patch('sys.argv', ['workbench']), patch('sys.stdin', input_stream), \
                     patch('sys.stdout', output):
                    main()
                reply = json.loads(raw.getvalue().decode('utf8'))
                self.assertEqual(reply['id'], 1)
                self.assertEqual(reply.get('error', reply.get('data')), str(response) if isinstance(response, Exception) else response)
                worker.dispatch.assert_called_once_with(frame)
                worker.close.assert_called_once()

    def test_lost_submission_can_find_retained_job_without_resubmitting(self):
        workbench = Workbench()
        workbench.client = Mock()
        retained = {'jobs': [{'job_id': 'b' * 32, 'request_id': 'saved-before-submit', 'state': 'running'}]}
        workbench.client.job_status.return_value = retained
        self.assertEqual(workbench.dispatch({'method': 'job.status', 'params': {}}), retained)
        workbench.client.job_status.assert_called_once_with(None)
        workbench.client.start_job.assert_not_called()
        workbench.dispatch({'method': 'job.status', 'params': {'job_id': 'b' * 32}})
        workbench.client.job_status.assert_called_with('b' * 32)

    def test_saved_inventory_never_returns_credentials_or_attaches(self):
        workbench = Workbench()
        with patch('mklink_remote.s3_registry.load_nodes', return_value={'s3-' + NODE['node_id']: NODE}):
            result = workbench.dispatch({'method': 'saved_nodes'})
        self.assertEqual(result, [{k: NODE[k] for k in ('node_id', 'transport', 'address')}])
        self.assertIsNone(workbench.client)

    def test_failed_detach_retires_client_without_replaying_close(self):
        workbench = Workbench()
        client = Mock()
        client.close.side_effect = ConnectionError('lost detach response')
        workbench.client = client
        with self.assertRaises(ConnectionError):
            workbench.close()
        self.assertIsNone(workbench.client)
        workbench.close()
        client.close.assert_called_once()

    def test_saved_attach_uses_only_registered_credentials(self):
        runtime = Mock()
        sites = Mock()
        with patch.dict(sys.modules, {'mklink.runtime': runtime, 'mklink.remote.sites': sites}):
            with patch('mklink_remote.s3_registry.load_nodes', return_value={'s3-' + NODE['node_id']: NODE}), \
                 patch('mklink_remote.s3_registry.validate_node', side_effect=RuntimeError('stop before device IO')) as validate:
                with self.assertRaisesRegex(RuntimeError, 'stop before device IO'):
                    Workbench().attach({'node_id': NODE['node_id'], 'token': 'untrusted'})
                validate.assert_called_once_with(NODE)
            with patch('mklink_remote.s3_registry.load_nodes', return_value={}):
                with self.assertRaisesRegex(ValueError, 'Saved node not found'):
                    Workbench().attach({'node_id': NODE['node_id']})
            with self.assertRaisesRegex(ValueError, 'not both'):
                Workbench().attach({'node_id': NODE['node_id'], 'node': NODE})
        runtime.ensure_runtime.assert_not_called()


if __name__ == '__main__':
    unittest.main()
