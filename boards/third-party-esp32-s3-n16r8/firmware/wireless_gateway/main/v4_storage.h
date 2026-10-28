#pragma once
#include "esp_err.h"
#include "cJSON.h"
#include <stdbool.h>
esp_err_t v4_storage_start(void);
void v4_storage_attach(unsigned address);
void v4_storage_detach(void);
bool v4_storage_ready(void);
bool v4_storage_upload_active(void);
void v4_storage_reconcile_owner(const char *owner);
cJSON *v4_storage_rpc(const char *method,const cJSON *params,const char *owner,int *code,const char **message);
