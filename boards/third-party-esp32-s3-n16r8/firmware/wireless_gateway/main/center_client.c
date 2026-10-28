/* Wire contract: HIL-Infra/hil_core/gateway.py and site_relay.py, read 2026-10-26.
 * Only actual bench.registered/pong marks the control channel online.
 * Probe operations remain unavailable until the V4 USB transport is admitted. */
#include "center_client.h"
#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "network_manager.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static SemaphoreHandle_t lock;
static node_settings_t config, connection_config;
static center_status_t status;
static unsigned generation;
static char message[2048];
static size_t used;
static esp_websocket_client_handle_t client;
static uint64_t heartbeat;
static uint64_t connected_at;
static unsigned ping_interval = 10000;
static bool registered;
static void take(void) { xSemaphoreTake(lock, portMAX_DELAY); }
static void give(void) { xSemaphoreGive(lock); }
static void send_json(cJSON *j) {
    char *raw = cJSON_PrintUnformatted(j);
    if (raw) {
        esp_websocket_client_send_text(client, raw, strlen(raw), pdMS_TO_TICKS(1500));
        free(raw);
    }
    cJSON_Delete(j);
}
void center_snapshot(center_status_t *out) {
    take();
    *out = status;
    give();
}
void center_configure(const node_settings_t *settings) {
    take();
    config = *settings;
    generation++;
    give();
}
static void event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    (void)base;
    if (id == WEBSOCKET_EVENT_CONNECTED) {
        node_settings_t c;
        take();
        c = connection_config;
        registered = false;
        connected_at = esp_timer_get_time() / 1000;
        strcpy(status.state, "registering");
        give();
        cJSON *j = cJSON_CreateObject();
        cJSON_AddStringToObject(j, "type", "bench.register");
        cJSON_AddStringToObject(j, "bench_id", c.bench_id);
        cJSON_AddStringToObject(j, "token", c.relay_token);
        cJSON_AddStringToObject(j, "version", "mklink-remote-0.4.1");
        cJSON_AddStringToObject(j, "hostname", c.node_name);
        cJSON *cap = cJSON_AddObjectToObject(j, "capabilities");
        cJSON_AddBoolToObject(cap, "chunked_artifact", false);
        cJSON_AddBoolToObject(cap, "renew", false);
        cJSON_AddBoolToObject(cap, "mklink_operations", false);
        send_json(j);
    } else if (id == WEBSOCKET_EVENT_DISCONNECTED || id == WEBSOCKET_EVENT_ERROR) {
        take();
        status.control_online = false;
        registered = false;
        strcpy(status.state, "disconnected");
        snprintf(status.error, sizeof(status.error),
                 "Control link unavailable; verify address, credentials and TLS time");
        give();
        used = 0;
    } else if (id == WEBSOCKET_EVENT_DATA) {
        esp_websocket_event_data_t *e = data;
        if (e->op_code != 1 && e->op_code != 0)
            return;
        if (e->payload_offset == 0)
            used = 0;
        if (e->payload_len <= 0 || e->payload_len >= (int)sizeof(message) || e->payload_offset != (int)used ||
            e->data_len < 0 || used + (size_t)e->data_len >= sizeof(message)) {
            used = 0;
            return;
        }
        memcpy(message + used, e->data_ptr, e->data_len);
        used += e->data_len;
        if ((int)used != e->payload_len || !e->fin)
            return;
        message[used] = 0;
        cJSON *j = memchr(message, 0, used) ? NULL : cJSON_ParseWithOpts(message, NULL, true);
        used = 0;
        cJSON *type = cJSON_GetObjectItemCaseSensitive(j, "type");
        if (cJSON_IsString(type)) {
            if (!strcmp(type->valuestring, "bench.registered") || !strcmp(type->valuestring, "pong")) {
                take();
                if (!strcmp(type->valuestring, "bench.registered")) {
                    registered = true;
                    cJSON *period = cJSON_GetObjectItemCaseSensitive(j, "heartbeat_s");
                    if (cJSON_IsNumber(period) && period->valuedouble >= 1 && period->valuedouble <= 300)
                        ping_interval = (unsigned)(period->valuedouble * 1000);
                }
                status.control_online = registered;
                status.operations_ready = false;
                strcpy(status.state, "control_online");
                status.error[0] = 0;
                heartbeat = esp_timer_get_time() / 1000;
                status.last_heartbeat_ms = heartbeat;
                give();
            } else if (!strcmp(type->valuestring, "session.open")) {
                take();
                snprintf(status.error, sizeof(status.error),
                         "Remote operation rejected: V4 USB transport not admitted; no action executed");
                give();
                /* No session.bind, fake locks or operation-success replies. The gateway
                 * fails its real session readiness deadline instead of executing unsafely. */
            }
        }
        cJSON_Delete(j);
    }
}
static void worker(void *arg) {
    (void)arg;
    unsigned active = 0;
    uint64_t ping_at = 0;
    for (;;) {
        node_settings_t c;
        unsigned revision;
        take();
        c = config;
        revision = generation;
        give();
        network_status_t net;
        network_snapshot(&net);
        bool ready = c.gateway_enabled && c.gateway_url[0] && c.bench_id[0] && c.relay_token[0] &&
                     !strcmp(net.sta_state, "connected");
        if (client && (!ready || active != revision)) {
            esp_websocket_client_stop(client);
            esp_websocket_client_destroy(client);
            client = NULL;
            take();
            status.control_online = false;
            give();
        }
        if (!ready) {
            take();
            strcpy(status.state, c.gateway_enabled ? "waiting_network" : "disabled");
            give();
        } else if (!strncmp(c.gateway_url, "wss://", 6) && time(NULL) < 1700000000) {
            take();
            strcpy(status.state, "waiting_clock");
            give();
        } else if (!client) {
            char uri[256];
            snprintf(uri, sizeof(uri), "%s/relay/control", c.gateway_url);
            esp_websocket_client_config_t ws = {.uri = uri,
                                                .buffer_size = 2048,
                                                .task_stack = 6144,
                                                .reconnect_timeout_ms = 5000,
                                                .network_timeout_ms = 5000,
                                                .crt_bundle_attach = esp_crt_bundle_attach};
            take();
            connection_config = c;
            give();
            client = esp_websocket_client_init(&ws);
            active = revision;
            if (client) {
                esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, event, NULL);
                esp_websocket_client_start(client);
                ping_at = esp_timer_get_time() / 1000;
            }
        }
        if (client && esp_websocket_client_is_connected(client)) {
            uint64_t now = esp_timer_get_time() / 1000;
            take();
            unsigned interval = ping_interval;
            give();
            if (now - ping_at >= interval) {
                cJSON *ping = cJSON_CreateObject();
                cJSON_AddStringToObject(ping, "type", "ping");
                cJSON_AddNumberToObject(ping, "ts", time(NULL));
                send_json(ping);
                ping_at = now;
            }
            take();
            if (status.control_online && now - heartbeat > 3 * interval) {
                status.control_online = false;
                strcpy(status.state, "heartbeat_lost");
            }
            bool timeout = registered ? !status.control_online : now - connected_at > 10000;
            give();
            if (timeout) {
                esp_websocket_client_stop(client);
                esp_websocket_client_destroy(client);
                client = NULL;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}
esp_err_t center_start(void) {
    lock = xSemaphoreCreateMutex();
    if (!lock)
        return ESP_ERR_NO_MEM;
    strcpy(status.state, "disabled");
    return xTaskCreate(worker, "center_client", 8192, NULL, 2, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
