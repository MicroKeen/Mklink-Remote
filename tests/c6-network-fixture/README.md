# C6 network fixture

Independent ESP32-C6 AP/STA fixture used to exercise S3 Wi-Fi without changing the host computer's Wi-Fi. This is optional HIL source, not part of the normal product firmware.

Back up the C6 first, identify the actual chip/Flash size, and preserve its original firmware. Build in an ESP-IDF 5.5.2 environment with `idf.py -C tests/c6-network-fixture build`. Provision and restore it only under an explicit hardware test plan. Never overwrite a user's C6 application as part of CI or repository setup.

See [HIL requirements](../../docs/TESTING.md). Raw historical campaign scripts and their device credentials/identities are not public test fixtures.
