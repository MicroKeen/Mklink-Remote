#pragma once
#include "esp_err.h"
#include "node_settings.h"
typedef struct {
    char requested[8], actual[8], sta_state[16], sta_ssid[33], ip[16], error[96], ap_ip[16], ap_ssid[33];
    int rssi, ap_clients; bool ap_active, switching;
} network_status_t;
esp_err_t network_start(const node_settings_t *settings);
esp_err_t network_schedule(const node_settings_t *settings);
void network_snapshot(network_status_t *out);
