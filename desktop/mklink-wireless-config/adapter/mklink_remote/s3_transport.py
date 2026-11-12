"""Native MKLink SDK over the authenticated S3 byte/file relay.

Only transport and file delivery are adapted. Device, Pika parsing, FLM,
memory access and RTT/MUX implementation come from the pinned MKLink runtime.
No OS WLAN calls, SWD implementation, retries, or global runtime edits.
"""
from __future__ import annotations

import base64
from collections import deque
import hashlib
from pathlib import Path
import struct
import threading
import time
import zlib

from mklink.bridge import MKLinkSerialBridge
from mklink._types import DeviceState



class _FifoRLock:
    """One RPC at a time, without a polling reader starving queued writes."""
    def __init__(self):
        self.condition=threading.Condition()
        self.waiters=deque()
        self.owner=None
        self.depth=0

    def __enter__(self):
        ident=threading.get_ident()
        with self.condition:
            if self.owner==ident:
                self.depth+=1
                return self
            ticket=object();self.waiters.append(ticket)
            try:
                self.condition.wait_for(lambda:self.owner is None and self.waiters[0] is ticket)
            except BaseException:
                self.waiters.remove(ticket);self.condition.notify_all();raise
            self.waiters.popleft();self.owner=ident;self.depth=1
        return self

    def __exit__(self,*_):
        with self.condition:
            if self.owner!=threading.get_ident():raise RuntimeError('RPC lock owner mismatch')
            self.depth-=1
            if not self.depth:
                self.owner=None;self.condition.notify_all()


class WirelessLink:
    def __init__(self, rpc, node_id, *, owner='Mklink wireless target', read_window_cap=None, pull_rpc=None):
        if len(node_id) != 12 or any(c not in '0123456789abcdef' for c in node_id):
            raise ValueError('Exact S3 device identity required')
        self.rpc = rpc
        self.pull_rpc = pull_rpc
        self.duplex = False
        self.zlib_pull = False
        self.zlib_reads = False
        self.pull_native_bytes = self.pull_encoded_bytes = self.compressed_pulls = 0
        self.pulling = False
        self.pull_sequence = 0
        self.open_sequence = None
        self.read_window_cap = read_window_cap
        self.node_id = node_id
        self.owner = owner
        self.lock = _FifoRLock()
        self.upload_lock = threading.Lock()
        self.lease = ''
        self.generation = None
        self.sequence = None
        self.poisoned = False
        self.opened = False
        self.renewed = 0
        self.stream_renews_lease = False
        self.recent_rpc = deque(maxlen=8)
        self.read_limit_supported=False;self.read_max=1024;self.file_chunk=1024
        self.hex_files_supported=False
        self.rpc_samples={};self.accepted_native_bytes=0;self.received_native_bytes=0;self.staged_file_bytes=0
        self.started=time.monotonic()

    def _timing(self,method,started,ok):
        ms=round((time.monotonic()-started)*1000,3)
        self.recent_rpc.append(dict(method=method,ms=ms,ok=ok))
        entry=self.rpc_samples.setdefault(method,dict(count=0,failures=0,total_ms=0.0,samples=[]))
        entry['count']+=1;entry['failures']+=not ok;entry['total_ms']+=ms
        if len(entry['samples'])<50000:entry['samples'].append(ms)

    def performance(self):
        import math
        methods={}
        for name,item in self.rpc_samples.items():
            values=sorted(item['samples']);n=len(values)
            methods[name]=dict(count=item['count'],failures=item['failures'],total_ms=round(item['total_ms'],3),
                p50_ms=values[max(0,math.ceil(n*.50)-1)],p95_ms=values[max(0,math.ceil(n*.95)-1)],
                max_ms=values[-1],samples_omitted=item['count']-n)
        return dict(scope='owned authenticated RPC session, payload bytes exclude JSON/encryption overhead',
            elapsed_s=round(time.monotonic()-self.started,3),read_window_bytes=self.read_max,file_chunk_bytes=self.file_chunk,
            native_tx_accepted_bytes=self.accepted_native_bytes,native_rx_bytes=self.received_native_bytes,
            file_payload_accepted_bytes=self.staged_file_bytes,methods=methods)

    def acquire(self, *, recover_stream=True):
        with self.lock:
            status = self.rpc('get_status', {})
            if status['device']['id'] != self.node_id:
                raise RuntimeError('Selected S3/V4 identity is not ready')
            if status.get('control', {}).get('owner'):
                state = self.rpc('get_probe_transport', {})
                if (recover_stream and state.get('state') == 'outcome_unknown' and
                        state.get('mux_recovery_supported') is True and state.get('mux_recoverable') is True):
                    # Quarantine retains the old 15-second lease; observe expiry before one new acquire.
                    deadline = time.monotonic() + 16
                    while (status['control']['owner'] and not status['control'].get('busy') and
                           time.monotonic() < deadline):
                        time.sleep(.25)
                        status = self.rpc('get_status', {})
                        if status['device']['id'] != self.node_id:
                            raise RuntimeError('S3 identity changed while waiting for lease expiry')
                if status['control']['owner']:
                    raise RuntimeError('S3 control is still held; wait for the previous session to release before reconnecting')
            if not status['probe']['ready']:
                if not recover_stream:
                    raise RuntimeError('Wireless recovery disabled for this connection')
                state = self.rpc('get_probe_transport', {})
                if not (state.get('state') == 'outcome_unknown' and
                        state.get('mux_recovery_supported') is True and state.get('mux_recoverable') is True):
                    raise RuntimeError('Selected S3/V4 requires explicit maintenance recovery')
            self.lease = self.rpc('control.acquire', {'owner': self.owner})['lease_token']
            self.renewed = time.monotonic()
            state = self.call('get_probe_transport')
            if state['state'] == 'outcome_unknown' and state.get('mux_recovery_supported') is True:
                if not recover_stream:
                    raise RuntimeError('Wireless recovery disabled for this connection')
                before = state['generation']
                recovered = self.call('probe.recover', {'generation': before})
                state = self.call('get_probe_transport')
                if (recovered.get('old_outcome_resolved') is not False or
                        state['generation'] != recovered.get('generation') or state['generation'] == before):
                    raise ConnectionError('MUX recovery generation not proven; no replay')
            if not state.get('binary_streaming') or state.get('stream_active') or state['state'] != 'ready':
                self.close()
                raise RuntimeError('Native stream requires compatible S3 firmware and an idle V4')
            self.generation = state['generation']
            self.stream_renews_lease = state.get('stream_renews_lease') is True
            self.duplex = self.pull_rpc is not None and state.get('independent_read_sequence') is True
            self.zlib_pull = self.duplex and state.get('zlib_pull_supported') is True
            self.zlib_reads = state.get('zlib_read_supported') is True
            self.sequence = state['next_sequence']
            self.read_limit_supported=state.get('read_limit_supported') is True
            if self.read_limit_supported:
                legacy=state.get('max_read_payload',1024)
                if type(legacy) is not int or not 1<=legacy<=4096:raise ValueError('Invalid legacy read window')
                self.read_max=state.get('bulk_read_max',legacy)
                if type(self.read_max) is not int or not legacy<=self.read_max<=32768:raise ValueError('Invalid negotiated read window')
            # PSRAM still buffers the full USB stream. Bound each BLE delivery
            # so a large ASCII reply cannot monopolize one GATT transaction.
            if self.read_window_cap is not None:
                cap = self.read_window_cap if self.zlib_reads else min(self.read_window_cap,4096)
                self.read_max=min(self.read_max,cap)
            self.usb_metrics_supported=state.get('usb_metrics_supported') is True
            self.native_binary_bulk=self.usb_metrics_supported and status['probe'].get('version')=='V4.7.2'
            self.file_chunk=state.get('file_chunk_max',1024)
            self.hex_files_supported=state.get('hex_files_supported') is True
            if type(self.file_chunk) is not int or not 1<=self.file_chunk<=2048:raise ValueError('Invalid negotiated file window')

    def renew_if_due(self):
        with self.lock:
            if self.lease and time.monotonic() - self.renewed > 3:
                started = time.monotonic()
                self.rpc('control.renew', {'lease_token': self.lease})
                self.renewed = started

    def call(self, method, params=None):
        with self.lock:
            if not self.lease:
                raise RuntimeError('No wireless target lease')
            self.renew_if_due()
            started=time.monotonic()
            try:
                result=self.rpc(method, dict(params or {}, lease_token=self.lease))
            except Exception:
                self._timing(method,started,False)
                raise
            self._timing(method,started,True)
            if self.stream_renews_lease and method in ('probe.stream.open', 'probe.stream.read', 'probe.stream.write', 'probe.stream.close'):
                self.renewed = started
            return result

    @staticmethod
    def _decode_reply(result, limit, allow_compressed):
        compressed = 'reply_zlib_base64' in result
        if compressed:
            size = result.get('uncompressed_bytes')
            if not allow_compressed or 'reply_base64' in result or type(size) is not int or not 1 <= size <= limit:
                raise ConnectionError('Invalid compressed read envelope')
            encoded = base64.b64decode(result['reply_zlib_base64'], validate=True)
            if not 0 < len(encoded) < size:
                raise ConnectionError('Invalid compressed read size')
            decoder = zlib.decompressobj()
            reply = decoder.decompress(encoded, size + 1)
            if len(reply) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ConnectionError('Incomplete or oversized compressed read')
        else:
            reply = encoded = base64.b64decode(result['reply_base64'], validate=True)
        if len(reply) > limit:
            raise ConnectionError('Oversized native stream response')
        return reply, encoded, compressed

    @staticmethod
    def _trace_read(result, reply, encoded, compressed, started):
        if len(reply) >= 4096 or time.monotonic()-started > .5:
            from mklink.connection_diagnostics import event
            event('remote.read', bytes=len(reply), encoded_bytes=len(encoded), compressed=compressed,
                  rpc_ms=round((time.monotonic()-started)*1000), read_us=result.get('read_us'),
                  compress_us=result.get('compress_us'), zip_stack_min=result.get('zip_stack_min'))

    def pull(self):
        with self.lock:
            if self.poisoned or not self.opened or not self.lease or self.pulling:
                raise ConnectionError('Independent read requires one healthy stream reader')
            self.renew_if_due()
            self.pull_sequence += 1
            # An independently delivered STOP cannot be overtaken by a stale read from a previous open.
            limit = self.read_max
            params = dict(lease_token=self.lease, generation=self.generation, open_sequence=self.open_sequence,
                          sequence=self.pull_sequence, max_bytes=limit)
            if self.zlib_pull:
                params['accept_zlib'] = True
            self.pulling = True
        started = time.monotonic()
        try:
            result = self.pull_rpc('probe.stream.pull', params)
            reply, encoded, compressed = self._decode_reply(result, limit, self.zlib_pull)
            with self.lock:
                if self.poisoned or result['generation'] != self.generation or len(reply) > limit:
                    raise ConnectionError('Invalid independent read response')
                self.received_native_bytes += len(reply)
                self.pull_native_bytes += len(reply)
                self.pull_encoded_bytes += len(encoded)
                self.compressed_pulls += compressed
                if self.stream_renews_lease:
                    self.renewed = max(self.renewed, started)
                self._timing('probe.stream.pull', started, True)
            self._trace_read(result, reply, encoded, compressed, started)
            return reply
        except Exception as error:
            with self.lock:
                self.poisoned = True
                self._timing('probe.stream.pull', started, False)
            raise ConnectionError('Independent read failed; no replay') from error
        finally:
            with self.lock:
                self.pulling = False

    def stream(self, action, data=None, *, interactive=False):
        if action == 'read' and interactive and self.duplex:
            return self.pull()
        submitted = time.monotonic()
        if action == 'write' and data and len(data) >= 20 and data[:4] == b'MLX1' and data[5] in (0x31, 0x35):
            from mklink.connection_diagnostics import event
            event('remote.stop_requested', opcode=data[5], epoch=int.from_bytes(data[8:12], 'little'), request=int.from_bytes(data[12:16], 'little'))
        with self.lock:
            if self.poisoned:
                raise ConnectionError('Native stream outcome unknown; no replay')
            if action == 'close' and self.pulling:
                raise ConnectionError('Native reader still owns IO')
            params = dict(generation=self.generation, sequence=self.sequence)
            # A long radio response blocks the sole MUX reader, including its heartbeat.
            limit = min(self.read_max, 4096) if interactive and not self.zlib_reads else self.read_max
            if action=='read' and self.read_limit_supported:params['max_bytes']=limit
            if action=='read' and self.zlib_reads:params['accept_zlib']=True
            if data is not None:
                if not 1 <= len(data) <= 1024:
                    raise ValueError('Native byte chunk must contain 1..1024 bytes')
                params['request_base64'] = base64.b64encode(data).decode('ascii')
            self.sequence += 1
            try:
                started = time.monotonic()
                result = self.call('probe.stream.' + action, params)
                if result['generation'] != self.generation:
                    raise ConnectionError('V4 generation changed during native stream')
                if data is not None and result['accepted_bytes'] != len(data):
                    raise ConnectionError('Partial native write; outcome unknown')
                reply, encoded, compressed = self._decode_reply(result, limit if action=='read' else 1024, action=='read' and self.zlib_reads)
                if data and len(data) >= 20 and data[:5] == b'MLX1\x01' and data[5] in (2, 0x31, 0x35):
                    from mklink.connection_diagnostics import event
                    epoch, request = struct.unpack_from('<II', data, 8)
                    event('remote.mux_write', opcode=data[5], epoch=epoch, request=request,
                          queue_ms=round((started-submitted)*1000), rpc_ms=round((time.monotonic()-started)*1000),
                          usb_start_us=result.get('usb_start_us'), usb_done_us=result.get('usb_done_us'),
                          pull_native_bytes=self.pull_native_bytes, pull_encoded_bytes=self.pull_encoded_bytes,
                          compressed_pulls=self.compressed_pulls)
                if action == 'read':
                    self._trace_read(result, reply, encoded, compressed, started)
                self.received_native_bytes+=len(reply)
                if data is not None:self.accepted_native_bytes+=len(data)
                if action == 'open':
                    self.opened = True
                    self.open_sequence = params['sequence']
                    self.pull_sequence = 0
                elif action == 'close':
                    self.opened = False
                return reply
            except Exception as error:
                self.poisoned = True
                raise ConnectionError('Native transport failed; no replay') from error

    def upload_file(self, path, kind, progress=None, expected_sha256=None):
        path = Path(path)
        if kind not in ('BIN', 'FLM', 'HEX') or not 1 <= path.stat().st_size <= 1048576:
            raise ValueError('Bounded BIN/HEX/FLM file required')
        if kind == 'HEX' and not self.hex_files_supported:
            raise ValueError('S3 firmware lacks HEX staging support; update the gateway')
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if not 1<=len(data)<=1048576 or (expected_sha256 is not None and digest!=expected_sha256):
            raise RuntimeError('Staging input changed from the acknowledged image; no file request sent')
        if progress:progress('upload',0,len(data))
        # Serialize staging without blocking the native reader or lease renewal.
        with self.upload_lock:
            if self.call('probe.files.status')['upload_active']:
                raise RuntimeError('An earlier upload is still active; detach all clients before recovery')
            ident = None
            try:
                result = self.call('probe.files.begin', dict(kind=kind, size=len(data), sha256=digest))
                if result['complete']:
                    if result['sha256'] != digest:
                        raise RuntimeError('Cached file digest mismatch')
                    if progress:progress('complete',len(data),len(data))
                    return result['path']
                ident = result['upload_id']
                # Each offset is sent once; only a verified commit permits programming.
                for offset in range(0, len(data), self.file_chunk):
                    chunk = data[offset:offset + self.file_chunk]
                    result = self.call('probe.files.write', dict(upload_id=ident, offset=offset,
                                       data_base64=base64.b64encode(chunk).decode('ascii')))
                    if result['offset'] != offset + len(chunk):
                        raise RuntimeError('File offset mismatch; upload not repeated')
                    self.staged_file_bytes+=len(chunk)
                    if progress:progress('upload',result['offset'],len(data))
                if progress:progress('verify',0,0)
                result = self.call('probe.files.commit', dict(upload_id=ident))
                if result['sha256'] != digest or result['bytes'] != len(data):
                    raise RuntimeError('Committed file identity mismatch')
                if progress:progress('complete',len(data),len(data))
                return result['path']
            except Exception as error:
                try:
                    state = self.call('probe.files.status')
                    if state['upload_active']:
                        owned = state['upload_id']
                        if not owned or (ident is not None and owned != ident):
                            raise RuntimeError('Upload identity changed')
                        # Abort only this lease's temporary staging, never a committed file or target write.
                        if self.call('probe.files.abort', {'upload_id': owned}).get('aborted') is not True:
                            raise RuntimeError('Upload abort not confirmed')
                except Exception as cleanup:
                    raise RuntimeError(f'{error}; upload cleanup unconfirmed: {cleanup}; detach all clients before recovery; no replay') from error
                raise

    def close(self):
        with self.lock:
            if self.opened:
                if self.poisoned:
                    # Explicitly quarantine; never inject a text stop into a
                    # possible binary packet or continue using another lease.
                    try:
                        self.call('probe.stream.abort')
                    except Exception:
                        pass
                    raise ConnectionError('Native session quarantined; explicit USB recovery required')
                self.stream('close')
            if self.lease:
                self.call('control.release')
                self.lease = ''


class WirelessSerial:
    """Minimal serial-shaped transport consumed by the SDK's sole reader."""
    def __init__(self, link):
        self.link = link
        self.timeout = .01
        self.write_timeout = 3
        self.buffer = bytearray()
        self._trace_rx = bytearray()
        self.is_open = False
        self.safe_close = lambda: True
        self.mux_active = lambda: False
        link.stream('open')
        self.is_open = True

    @property
    def in_waiting(self):
        return len(self.buffer) or 1024

    def read(self, size=1):
        if not self.is_open:
            raise ConnectionError('Wireless stream closed')
        if not self.buffer:
            incoming = self.link.stream('read', interactive=True) if self.mux_active() else self.link.stream('read')
            self.buffer.extend(incoming)
            if self.mux_active():
                self._observe_replies(incoming)
            else:
                self._trace_rx.clear()
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def _observe_replies(self, data):
        # Diagnostics only; never change the native byte stream or acknowledge a command.
        import binascii
        from mklink.connection_diagnostics import event
        buf = self._trace_rx
        buf.extend(data)
        while len(buf) >= 20:
            if buf[:4] != b'MLX1' or buf[4] != 1:
                del buf[0]
                continue
            length = int.from_bytes(buf[6:8], 'little')
            if length > 1040:
                del buf[0]
                continue
            total = length + 20
            if len(buf) < total:
                break
            if binascii.crc32(buf[:total-4]) & 0xffffffff != int.from_bytes(buf[total-4:total], 'little'):
                del buf[0]
                continue
            if buf[5] in (0x82, 0xB1, 0xB5):
                event('remote.mux_reply', opcode=buf[5], epoch=int.from_bytes(buf[8:12], 'little'),
                      request=int.from_bytes(buf[12:16], 'little'), status=buf[16] if length else None)
            del buf[:total]

    def write(self, data):
        if not self.is_open:
            raise ConnectionError('Wireless stream closed')
        for offset in range(0, len(data), 1024):
            self.link.stream('write', data[offset:offset + 1024])
        return len(data)

    def flush(self):
        # Each write is acknowledged after the complete USB transmission.
        return None

    def reset_input_buffer(self):
        raise RuntimeError('Discarding an active native stream is forbidden')

    def reset_output_buffer(self):
        return None  # No queued or retried writes exist.

    def close(self):
        if self.is_open:
            if not self.safe_close():
                self.link.poisoned = True
            if not self.link.poisoned:
                self.link.stream('close')
            self.is_open = False


class WirelessBridge(MKLinkSerialBridge):
    def __init__(self, link):
        super().__init__('s3-' + link.node_id)
        self.auto_recovery = False
        self.allow_algorithm_fallback = False
        self.require_reader_exit = True
        self.command_timeout_floor = 60.0
        self.transport_kind = 's3'
        # BLE RPCs stay serialized, but delayed PING replies must not reserve STOP's slot.
        self.mux_background_heartbeats = True
        self.capture_stop_timeout = 30.0
        self.reader_close_timeout = 35.0
        self.mux_timeout = 60.0
        self.stream_stop_attempts = 1
        self.stream_stop_timeout = 5.0
        self.stream_identity_timeout = 10.0
        from mklink.hil_lock import HilFileLock
        self._hil_locks = [HilFileLock('device_mklink-wireless-' + link.node_id, lease_s=60),
                           HilFileLock('transport_mklink-rpc_' + link.node_id, lease_s=60)]
        self._held_locks = []
        self._endpoint = None
        self._pull_endpoint = None
        self._lease_stop = threading.Event()
        self._lease_thread = None
        self.link = link
        self._staged_firmware = None
        self._retired = False

    @property
    def transport_healthy(self):
        return super().transport_healthy and not self.link.poisoned

    def send_command(self,cmd,timeout=5.0,**kwargs):
        try:
            return super().send_command(cmd,timeout=timeout,**kwargs)
        except Exception as error:
            if hasattr(error, 'add_note'):
                error.add_note('Wireless RPC timings (no payloads): '+str(list(self.link.recent_rpc)))
            raise

    def _connect(self, *, recover_stream=False):
        # Physical identity is already established by the authenticated S3 and
        # V4 descriptor/marker/version handshake. Do not discover a PC USB port,
        # or reconcile DAP ownership on another device. S3 owns bounded recovery.
        from mklink.probes import require_runtime_port
        require_runtime_port(self._port)
        for lock in self._hil_locks:
            lock.acquire()
            self._held_locks.append(lock)
        if not self._port_lock.acquire():
            raise ConnectionError('S3 transport already owned')
        if self._endpoint is not None:
            self._endpoint.open()
        if self._pull_endpoint is not None:
            self._pull_endpoint.open()
        self.link.acquire(recover_stream=recover_stream)
        def renew():
            next_renew = time.monotonic() + 2
            while not self._lease_stop.wait(.2):
                try:
                    if time.monotonic() >= next_renew:
                        if not all(lock.renew() for lock in self._held_locks):
                            raise ConnectionError('Wireless hardware ownership lost')
                        self.link.renew_if_due()
                        next_renew = time.monotonic() + 2
                    mux = self._mux
                    if mux is not None:
                        mux.tick()
                except Exception:
                    self.link.poisoned = True
                    return
        self._lease_thread = threading.Thread(target=renew, daemon=True)
        self._lease_thread.start()
        self._serial = WirelessSerial(self.link)
        self._serial.mux_active = lambda: self._mux is not None
        self._ctx.state = DeviceState.CONNECTING
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self._prompt_event.clear()
        self._serial.write(b'\n')
        if not self._prompt_event.wait(30):
            self.link.poisoned = True
            raise ConnectionError('Wireless Pika synchronization timed out; no replay')
        self._ctx.state = DeviceState.READY
        if not self._verify_identity():
            raise ConnectionError('Native MKLink identity verification failed')
        self.last_connect_error = None
        return True

    def close(self):
        if self._retired:
            return
        mux = self._mux
        if self._serial is not None:
            self._serial.safe_close = lambda: self._transport_error is None and self._ctx.state is not DeviceState.ERROR and (mux is None or mux._error is None)
        if self._transport_error is not None or self._ctx.state is DeviceState.ERROR or (mux is not None and mux._error is not None):
            self.link.poisoned = True
        self._lease_stop.set()
        if self._lease_thread:
            self._lease_thread.join(timeout=35)
            if self._lease_thread.is_alive():
                raise ConnectionError('Wireless lease worker still owns IO')
        # Do not close the event loop or release HIL ownership if the reader
        # failed to exit. The caller can inspect and explicitly recover it.
        super().close()
        try:
            self.link.close()
        except ConnectionError:
            if not self.link.poisoned:
                raise
            # Remote quarantine is retained by S3. It must not prevent retiring
            # a fully stopped local owner before a new recovery session.
            self.last_connect_error = 'Remote session quarantined; reconnect for supported MUX recovery'
        finally:
            if self._pull_endpoint:
                self._pull_endpoint.close()
            if self._endpoint:
                self._endpoint.close()
            for lock in reversed(self._held_locks):
                lock.release()
            self._held_locks.clear()
            self._retired = True

    @classmethod
    def from_node(cls, node):
        from mklink_remote.s3_rpc import Endpoint
        endpoint = Endpoint(node)
        pull_endpoint = None if node['transport']=='ble' else Endpoint(node)
        bridge = cls(WirelessLink(endpoint.rpc, node['node_id'], owner='MKLink shared backend', read_window_cap=16384 if node['transport']=='ble' else None,
                                  pull_rpc=pull_endpoint.rpc if pull_endpoint else None))
        bridge._endpoint = endpoint
        bridge._pull_endpoint = pull_endpoint
        return bridge

    def upload_algorithm(self, algorithm):
        from mklink.cmsis_dap.algorithm_catalog import _extract_bytes
        import tempfile
        with tempfile.TemporaryDirectory(prefix='s3-flm-') as directory:
            path = Path(directory) / 'algorithm.flm'
            path.write_bytes(_extract_bytes(algorithm))
            return self.link.upload_file(path, 'FLM')

    def prepare_firmware(self, path):
        from mklink.file_content import is_metadata_file
        if is_metadata_file(path):
            raise ValueError('Invalid firmware file')
        path = Path(path).resolve(strict=True)
        kind = path.suffix[1:].upper()
        if kind not in ('BIN', 'HEX') or not 1 <= path.stat().st_size <= 1048576:
            raise ValueError('Bounded BIN or Intel HEX firmware required')
        data = path.read_bytes()
        if not 1 <= len(data) <= 1048576:
            raise ValueError('Firmware size changed before staging')
        if kind == 'HEX':
            from io import StringIO
            from intelhex import IntelHex
            if not IntelHex(StringIO(data.decode('ascii'))).segments():
                raise ValueError('Intel HEX firmware contains no data')
        digest = hashlib.sha256(data).hexdigest()
        # Preserve HEX address records and gaps; native MKLink selects/validates sectors.
        remote = self.link.upload_file(path, kind, expected_sha256=digest)
        self._staged_firmware = (path, digest, remote)

    def upload_firmware(self, path):
        path = Path(path).resolve(strict=True)
        if self._staged_firmware is None:
            self.prepare_firmware(path)
        staged, digest, remote = self._staged_firmware
        if path != staged or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Firmware changed after staging; no program command sent')
        return remote
