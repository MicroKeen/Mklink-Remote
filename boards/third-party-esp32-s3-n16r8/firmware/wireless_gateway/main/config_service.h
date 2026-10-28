#pragma once
#include "esp_err.h"
#include "probe_transport.h"
esp_err_t config_service_start(void);
/* Future CDC driver calls from a task after identity/interface validation. */
bool config_bind_probe(const probe_descriptor_t *descriptor,const probe_backend_t *backend);
void config_unbind_probe(void);
