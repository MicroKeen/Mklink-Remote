# ESP-IDF USB Host MSC 1.2.0

Vendored from Espressif's ESP Component Registry. Upstream commit
[e40c964](https://github.com/espressif/esp-usb/tree/e40c96437e540b69ff49e0573ed9f02bc46a79be/host/class/msc/usb_host_msc).
The local patch reserves the transfer before sending the BOT command and
keeps the existing transfer valid if allocation fails. See LICENCE for
Apache-2.0 terms.
