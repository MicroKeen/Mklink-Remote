"""One owned target-helper connection using the shared Remote adapter."""
from contextlib import contextmanager
import sys
from unittest.mock import patch
from mklink.runtime import VERSION as NATIVE_SDK_VERSION
from mklink.device import Device
from mklink_remote.s3_transport import WirelessLink, WirelessBridge


@contextmanager
def native_device(link, *, project_root, axf=None, multiplex=True):
    device = Device(port='s3-' + link.node_id, project_root=str(project_root),
                    axf=str(axf) if axf else None, mcu='STM32F411CEUx')
    bridge = WirelessBridge(link)
    def selected_bridge(port, **options):
        if port != 's3-' + link.node_id:
            raise ConnectionError('Target helper cannot switch its selected relay')
        return bridge
    try:
        # The isolated helper owns one broker connection, not a registry endpoint.
        with patch('mklink.transport_factory.create_bridge', selected_bridge):
            device._connect()
        device._flash.set_swd_clock(1000000)
        device._wireless_text_reads = not multiplex
        device._wireless_bulk_size = 4096 if link.read_max >= 4096 else 1024
        device._wireless_binary_bulk = getattr(link, 'native_binary_bulk', False) is True
        if multiplex and device._bridge.enable_multiplex() is None:
            raise RuntimeError('V4 does not advertise native MUX target operations')
        yield device
    finally:
        original = sys.exc_info()[1]
        try:
            device.close()
        finally:
            try:
                bridge.close()
            except Exception as error:
                if original is None:
                    raise
                original.add_note('Wireless cleanup failed; explicit recovery required: ' + str(error))
