idf_component_register(
    SRCS "app_main.c" "gateway_memory.c" "firmware_update.c" "config_rpc.c" "node_policy.c" "network_manager.c" "center_client.c" "board_controls.c" "ble_config.c" "probe_transport.c" "usb_monitor.c" "v4_backend.c" "v4_storage.c" "descriptor_check.c"
    INCLUDE_DIRS "."
    REQUIRES usb probe_protocol app_update bootloader_support esp_psram esp_app_format esp_hw_support spi_flash esp_timer esp_wifi esp_netif esp_event nvs_flash esp_http_server json esp_driver_gpio esp_driver_rmt lwip mbedtls esp_websocket_client bt
    EMBED_TXTFILES "device.html"
)
