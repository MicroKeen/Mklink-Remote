# Third-party ESP32-S3 N16R8

16 MiB Flash / 8 MiB PSRAM wireless USB-host bridge for MicroLink V4. This is not the official ESP32-S3 USB-OTG board.

- Firmware: `firmware/wireless_gateway`, ESP-IDF 5.5.2.
- [Wiring and hardware scope](../../docs/HARDWARE.md).
- [Build](../../docs/BUILD.md) and [qualification](../../docs/VALIDATION-0.8.0.md).
- Vendor archives, schematics supplied privately, raw logs and Flash backups are retained locally and are not redistributed here.

USB1 is the USB-UART maintenance port. USB2 is the native USB-OTG host port. BOOT uses GPIO0, RGB uses GPIO48. Verify the board revision and power wiring before connecting the OTG solder bridge or a powered peripheral.
