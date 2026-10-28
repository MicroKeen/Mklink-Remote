#pragma once
#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>
typedef struct { bool enabled,connected; unsigned requests,auth_failures;
    unsigned reply_alloc_failures,rpc_response_failures,reply_crypto_failures,notify_retries,notify_failures,notify_fragments;
    unsigned last_request_sequence,last_reply_sequence,last_reply_bytes;int last_notify_error;
} ble_config_status_t;
esp_err_t ble_config_start(const char *device_name);
void ble_config_snapshot(ble_config_status_t *out);
void config_ble_key(uint8_t out[16]);
char *config_ble_rpc(const char *body);
