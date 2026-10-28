#pragma once
#include "node_settings.h"
#include "esp_err.h"
typedef struct {char state[24], error[128]; bool control_online, operations_ready; unsigned last_heartbeat_ms;} center_status_t;
esp_err_t center_start(void);
void center_configure(const node_settings_t *settings);
void center_snapshot(center_status_t *out);
