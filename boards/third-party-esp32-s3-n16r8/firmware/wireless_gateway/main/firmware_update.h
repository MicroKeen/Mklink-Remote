#pragma once
#include "cJSON.h"
#include "esp_err.h"
#include <stdbool.h>
/* Lock order: config RPC -> update guard. Worker never takes config RPC. */
esp_err_t firmware_update_init(void);
void firmware_update_health_ready(void);
bool firmware_update_busy(void);
cJSON *firmware_update_status(void);
cJSON *firmware_update_rpc(const char *method,const cJSON *params,const char *owner,int *code,const char **message);
