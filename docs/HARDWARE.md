# Supported hardware and wiring

The qualified board is the **third-party ESP32-S3 N16R8** (16 MiB Flash, 8 MiB PSRAM), not the official ESP32-S3 USB-OTG development kit. Do not interchange their firmware or power-control assumptions.

| Board connection | Use |
|---|---|
| USB1, white cable in the help photo | USB-UART maintenance, configuration, power and logs |
| USB2, black cable in the help photo | Native USB OTG host to MicroLink V4 |
| BOOT / GPIO0 | Firmware mode gestures; also the chip's boot strap |
| RGB / GPIO48 | Firmware mode/status indication; interactive legend in Help |

Use the board's USB-OTG solder bridge and an OTG adapter only after checking the actual board revision and its power wiring. The photograph identifies the ports; it is not a schematic or universal Type-C power guarantee. USB1 uses a USB-UART bridge, not native USB-JTAG.

Connect V4 SWDIO, SWCLK, GND and VTref to the powered target according to its schematic. The qualified target was STM32F411; V4 firmware 4.7.2 exposed valid 64-byte Full Speed command endpoints. Other targets and revisions require separate qualification.

First use: install the board-specific firmware with the workbench's backup-first installer, pair via USB1, then configure AP/STA or BLE. Save the original backup outside the repository. The default AP is `MklinkRemote-XXXXXX` derived from device identity; its password and management credential are device-specific. Do not assume a shared default password.

When testing AP/STA without disturbing the host's internet connection, use an independently provisioned ESP32-C6 fixture. It requires its own backup and restoration procedure; ordinary CI never flashes either board.
