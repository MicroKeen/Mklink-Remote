#pragma once
#include <stdbool.h>
#include <stdint.h>
#define NODE_SETTINGS_MAGIC 0x53474332u
typedef struct {
    uint32_t magic, revision;
    char node_name[64], ssid[33], password[65], gateway_url[192], token[33], last_change_id[65];
    char network_mode[8], ap_ssid[33], ap_password[64], bench_id[64], relay_token[129];
    bool gateway_enabled;
} node_settings_t;
