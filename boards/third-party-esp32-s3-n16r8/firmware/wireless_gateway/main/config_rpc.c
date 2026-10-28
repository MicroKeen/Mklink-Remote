#include "ble_config.h"
#include "board_controls.h"
#include "cJSON.h"
#include "center_client.h"
#include "config_service.h"
#include "esp_app_desc.h"
#include "esp_check.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_heap_caps.h"
#include "esp_psram.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "lwip/sockets.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "network_manager.h"
#include "node_policy.h"
#include "node_settings.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "usb_monitor.h"
#include "v4_backend.h"
#include "v4_storage.h"
#include "firmware_update.h"
#include <ctype.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static node_settings_t settings;
static control_lease_t lease;
static probe_transport_t probe;
/* Protected by rpc_lock; these are CPU workspaces, never USB DMA buffers. */
static struct {uint8_t input[PROBE_PAYLOAD_MAX],output[PROBE_READ_MAX];unsigned char encoded[((PROBE_READ_MAX+2)/3)*4+1];} *stream_workspace;
static SemaphoreHandle_t config_lock, rpc_lock;
static nvs_handle_t storage;
static char device_id[13];
static char events[24][128];
static unsigned event_count;
static uint64_t now_ms(void) { return esp_timer_get_time() / 1000; }
static void record(const char *text) {
    snprintf(events[event_count++ % 24], 128, "%llu %s", (unsigned long long)now_ms(), text);
    ESP_LOGI("config", "%s", text);
}
static void random_hex(char *out, unsigned bytes) {
    uint8_t raw[32];
    esp_fill_random(raw, bytes);
    for (unsigned i = 0; i < bytes; i++)
        snprintf(out + i * 2, 3, "%02x", raw[i]);
}
static void snapshot(node_settings_t *out) {
    xSemaphoreTake(config_lock, portMAX_DELAY);
    *out = settings;
    xSemaphoreGive(config_lock);
}
static bool string_field(const cJSON *p, const char *key, char *out, size_t size, bool required) {
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(p, key);
    if (!v)
        return !required;
    if (!cJSON_IsString(v) || !v->valuestring || strlen(v->valuestring) >= size)
        return false;
    strcpy(out, v->valuestring);
    return true;
}
void config_ble_key(uint8_t out[16]) {
    node_settings_t c;
    snapshot(&c);
    for (unsigned i = 0; i < 16; i++) {
        unsigned value = 0;
        sscanf(c.token + 2 * i, "%2x", &value);
        out[i] = value;
    }
    memset(&c, 0, sizeof(c));
}
static const char *str(const cJSON *p, const char *key) {
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(p, key);
    return cJSON_IsString(v) ? v->valuestring : NULL;
}
static bool password_valid(const char *p, bool ap) {
    size_t n = strlen(p);
    if (ap)
        return n >= 8 && n <= 63;
    if (!n || (n >= 8 && n <= 63))
        return true;
    if (n != 64)
        return false;
    for (unsigned i = 0; i < 64; i++)
        if (!isxdigit((unsigned char)p[i]))
            return false;
    return true;
}
static bool mode_valid(const char *m) {
    return !strcmp(m, "AP") || !strcmp(m, "STA") || !strcmp(m, "AP+STA");
}
static cJSON *config_json(void) {
    node_settings_t c;
    snapshot(&c);
    cJSON *j = cJSON_CreateObject();
    cJSON_AddNumberToObject(j, "revision", c.revision);
    cJSON_AddStringToObject(j, "last_change_id", c.last_change_id);
    cJSON_AddStringToObject(j, "node_name", c.node_name);
    cJSON_AddStringToObject(j, "wifi_ssid", c.ssid);
    cJSON_AddBoolToObject(j, "password_set", c.password[0] != 0);
    cJSON_AddStringToObject(j, "network_mode", c.network_mode);
    cJSON_AddStringToObject(j, "ap_ssid", c.ap_ssid);
    cJSON_AddBoolToObject(j, "ap_password_set", c.ap_password[0] != 0);
    cJSON_AddStringToObject(j, "gateway_url", c.gateway_url);
    cJSON_AddBoolToObject(j, "gateway_enabled", c.gateway_enabled);
    cJSON_AddStringToObject(j, "bench_id", c.bench_id);
    cJSON_AddBoolToObject(j, "relay_token_set", c.relay_token[0] != 0);
    return j;
}
static cJSON *status_json(void) {
    network_status_t n;
    network_snapshot(&n);
    center_status_t center;
    center_snapshot(&center);
    usb_monitor_status_t u;
    usb_monitor_snapshot(&u);
    node_settings_t c;
    snapshot(&c);
    lease_expire(&lease, now_ms());
    cJSON *j = cJSON_CreateObject(), *d = cJSON_AddObjectToObject(j, "device"),
          *w = cJSON_AddObjectToObject(j, "wifi"), *ap = cJSON_AddObjectToObject(j, "ap"),
          *usb = cJSON_AddObjectToObject(j, "usb"), *g = cJSON_AddObjectToObject(j, "gateway"),
          *owner = cJSON_AddObjectToObject(j, "control");
    ble_config_status_t ble;
    ble_config_snapshot(&ble);
    cJSON *b = cJSON_AddObjectToObject(j, "ble");
    cJSON_AddBoolToObject(b, "enabled", ble.enabled);
    cJSON_AddBoolToObject(b, "connected", ble.connected);
    cJSON_AddNumberToObject(b, "requests", ble.requests);
    cJSON_AddNumberToObject(b, "auth_failures", ble.auth_failures);
    cJSON_AddNumberToObject(b,"notify_retries",ble.notify_retries);
    cJSON_AddNumberToObject(b,"notify_failures",ble.notify_failures);
    cJSON_AddNumberToObject(b,"notify_fragments",ble.notify_fragments);
    cJSON_AddNumberToObject(b,"last_notify_error",ble.last_notify_error);
    cJSON_AddNumberToObject(b,"reply_alloc_failures",ble.reply_alloc_failures);
    cJSON_AddNumberToObject(b,"reply_crypto_failures",ble.reply_crypto_failures);
    cJSON_AddNumberToObject(b,"rpc_response_failures",ble.rpc_response_failures);
    cJSON_AddNumberToObject(b,"last_request_sequence",ble.last_request_sequence);
    cJSON_AddNumberToObject(b,"last_reply_sequence",ble.last_reply_sequence);
    cJSON_AddNumberToObject(b,"last_reply_bytes",ble.last_reply_bytes);
    cJSON_AddStringToObject(d, "id", device_id);
    cJSON_AddStringToObject(d, "board", "ESP32-S3 N16R8");
    cJSON_AddStringToObject(d, "firmware", esp_app_get_description()->version);
    cJSON_AddNumberToObject(d, "uptime_ms", now_ms());
    cJSON_AddNumberToObject(d, "free_heap", esp_get_free_heap_size());
    cJSON_AddNumberToObject(d,"psram_bytes",esp_psram_get_size());
    cJSON_AddNumberToObject(d,"free_psram",heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    cJSON_AddNumberToObject(d,"free_internal",heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
    cJSON_AddNumberToObject(d,"largest_internal",heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
    cJSON_AddItemToObject(j,"firmware_update",firmware_update_status());
    cJSON_AddStringToObject(j, "network_mode", n.actual);
    cJSON_AddStringToObject(j, "preferred_mode", c.network_mode);
    cJSON_AddBoolToObject(j, "switching", n.switching);
    cJSON_AddStringToObject(w, "state", n.sta_state);
    cJSON_AddStringToObject(w, "ssid", n.sta_ssid);
    cJSON_AddStringToObject(w, "ip", n.ip);
    cJSON_AddNumberToObject(w, "rssi", n.rssi);
    wifi_ps_type_t power_save;
    if(esp_wifi_get_ps(&power_save)==ESP_OK)cJSON_AddStringToObject(w,"power_save",power_save==WIFI_PS_NONE?"none":"modem");
    cJSON_AddStringToObject(w, "error", n.error);
    cJSON_AddBoolToObject(ap, "active", n.ap_active);
    cJSON_AddStringToObject(ap, "ssid", n.ap_ssid);
    cJSON_AddStringToObject(ap, "ip", n.ap_ip);
    cJSON_AddNumberToObject(ap, "clients", n.ap_clients);
    cJSON_AddBoolToObject(usb, "connected", u.connected);
    cJSON_AddNumberToObject(usb, "vid", u.vid);
    cJSON_AddNumberToObject(usb, "pid", u.pid);
    cJSON_AddStringToObject(usb, "speed",
                            u.connected ? (u.speed == 1   ? "FULL_12Mbps"
                                           : u.speed == 0 ? "LOW_1.5Mbps"
                                                          : "HIGH_480Mbps")
                                        : "NONE");
    cJSON_AddNumberToObject(usb, "invalid_bulk", u.invalid_bulk);
    cJSON_AddNumberToObject(usb, "interfaces", u.interfaces);
    cJSON_AddNumberToObject(usb, "endpoints", u.endpoints);
    v4_backend_status_t backend;
    v4_backend_snapshot(&backend);
    cJSON *transport=cJSON_AddObjectToObject(j,"probe");
    cJSON_AddStringToObject(transport,"state",probe.dirty?"outcome_unknown":backend.state);
    cJSON_AddStringToObject(transport,"version",backend.version);
    cJSON_AddStringToObject(transport,"error",backend.error);
    cJSON_AddNumberToObject(transport,"generation",probe.generation);
    cJSON_AddNumberToObject(transport,"in_mps",backend.in_mps);
    cJSON_AddNumberToObject(transport,"out_mps",backend.out_mps);
    cJSON_AddNumberToObject(transport,"rx_pending",backend.rx_pending);
    cJSON_AddNumberToObject(transport,"rx_peak",backend.rx_peak);
    cJSON_AddNumberToObject(transport,"rx_capacity",backend.rx_capacity);
    cJSON_AddNumberToObject(transport,"rx_overflows",backend.rx_overflows);
    cJSON_AddBoolToObject(transport,"ready",probe.ready&&!probe.dirty&&!strcmp(backend.state,"ready"));
    cJSON_AddStringToObject(g, "state", center.state);
    cJSON_AddStringToObject(g, "url", c.gateway_url);
    cJSON_AddBoolToObject(g, "control_online", center.control_online);
    cJSON_AddBoolToObject(g, "operations_ready", false);
    cJSON_AddStringToObject(g, "error", center.error);
    cJSON_AddStringToObject(owner, "owner", lease.owner);
    cJSON_AddBoolToObject(owner, "busy", lease.busy);
    cJSON_AddNumberToObject(owner, "remaining_ms",
                            lease.expires_ms > now_ms() ? lease.expires_ms - now_ms() : 0);
    return j;
}
static cJSON *failure(const cJSON *id, int code, const char *message) {
    cJSON *j = cJSON_CreateObject();
    cJSON_AddNumberToObject(j, "v", 1);
    cJSON_AddItemToObject(j, "id", id ? cJSON_Duplicate(id, true) : cJSON_CreateNull());
    cJSON_AddBoolToObject(j, "ok", false);
    cJSON *e = cJSON_AddObjectToObject(j, "error");
    cJSON_AddNumberToObject(e, "code", code);
    cJSON_AddStringToObject(e, "message", message);
    return j;
}
static bool authorized(const cJSON *p) { return lease_authorized(&lease, str(p, "lease_token"), now_ms()); }
static esp_err_t persist(const node_settings_t *next) {
    esp_err_t err = nvs_set_blob(storage, "settings", next, sizeof(*next));
    if (err == ESP_OK)
        err = nvs_commit(storage);
    if (err == ESP_OK) {
        xSemaphoreTake(config_lock, portMAX_DELAY);
        settings = *next;
        xSemaphoreGive(config_lock);
    }
    return err;
}
static cJSON *dispatch(const cJSON *request, bool serial) {
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(request, "id"),
                *version = cJSON_GetObjectItemCaseSensitive(request, "v"),
                *method = cJSON_GetObjectItemCaseSensitive(request, "method"),
                *p = cJSON_GetObjectItemCaseSensitive(request, "params");
    if (!cJSON_IsObject(request) || !cJSON_IsString(id) || !id->valuestring[0] ||
        strlen(id->valuestring) > 64 || !cJSON_IsNumber(version) || version->valuedouble != 1 ||
        !cJSON_IsString(method) || !cJSON_IsObject(p))
        return failure(id, 400, "Invalid configuration request");
    const char *m = method->valuestring;
    lease_expire(&lease,now_ms());
    probe_transport_reconcile_owner(&probe,lease.owner[0]?lease.token:NULL);
    v4_storage_reconcile_owner(lease.owner[0]?lease.token:NULL);
    if(firmware_update_busy()&&strncmp(m,"firmware.",9)&&strncmp(m,"control.",8)&&
       strcmp(m,"get_status")&&strcmp(m,"get_config")&&strcmp(m,"get_logs")&&strcmp(m,"get_probe_transport"))
        return failure(id,423,"Node firmware update is exclusive; finish or abort before other operations");
    cJSON *result = NULL;
    if (!strcmp(m, "get_probe_transport")) {
        usb_monitor_status_t u;
        usb_monitor_snapshot(&u);
        result = cJSON_CreateObject();
        v4_backend_status_t backend;v4_backend_snapshot(&backend);
        const char *transport_state=probe.dirty||!strcmp(backend.state,"quarantined")?"outcome_unknown":
            probe.ready&&!strcmp(backend.state,"ready")?"ready":u.invalid_bulk?"awaiting_v4_firmware":backend.state;
        cJSON_AddStringToObject(result,"state",transport_state);
        cJSON_AddNumberToObject(result, "generation", probe.generation);
        cJSON_AddNumberToObject(result, "max_payload", PROBE_PAYLOAD_MAX);
        cJSON_AddNumberToObject(result, "max_request_bytes",511);
        cJSON_AddStringToObject(result,"framing","pika_prompt_v1");
        cJSON_AddBoolToObject(result,"binary_streaming",probe.backend.stream!=NULL);
        cJSON_AddBoolToObject(result,"stream_active",probe.stream_active);
        cJSON_AddStringToObject(result,"stream_framing","mklink_native_bytes_v1");
        cJSON_AddBoolToObject(result,"storage_ready",v4_storage_ready());
        cJSON_AddBoolToObject(result,"read_limit_supported",true);
        cJSON_AddNumberToObject(result,"max_read_payload",4096); /* Legacy clients retain their4KiB guard. */
        cJSON_AddNumberToObject(result,"bulk_read_max",PROBE_READ_MAX);
        cJSON_AddBoolToObject(result,"usb_metrics_supported",true);
        cJSON_AddNumberToObject(result,"file_chunk_max",2048);
        cJSON_AddNumberToObject(result,"next_sequence",!strcmp(probe.controller,lease.token)?(double)probe.last_sequence+1:1);
        cJSON_AddStringToObject(result, "encoding", "base64_opaque_bytes_v1");
        cJSON_AddBoolToObject(result, "automatic_replay", false);
    } else if (!strcmp(m, "get_status"))
        result = status_json();
    else if (!strcmp(m, "get_config"))
        result = config_json();
    else if (!strcmp(m, "get_logs")) {
        result = cJSON_CreateArray();
        unsigned first = event_count > 24 ? event_count - 24 : 0;
        for (unsigned i = first; i < event_count; i++)
            cJSON_AddItemToArray(result, cJSON_CreateString(events[i % 24]));
    } else if (!strcmp(m, "pair")) {
        if (!serial)
            return failure(id, 403, "Initial pairing requires USB1");
        node_settings_t c;
        snapshot(&c);
        network_status_t n;
        network_snapshot(&n);
        result = cJSON_CreateObject();
        cJSON_AddStringToObject(result, "token", c.token);
        cJSON_AddStringToObject(result, "ap_ssid", c.ap_ssid);
        cJSON_AddStringToObject(result, "ap_password", c.ap_password);
        cJSON_AddStringToObject(result, "ap_ip", n.ap_ip[0] ? n.ap_ip : "192.168.4.1");
        cJSON_AddNumberToObject(result, "port", 80);
    } else if (!strcmp(m, "control.acquire")) {
        char token[33];
        random_hex(token, 16);
        const char *owner = str(p, "owner");
        if (!lease_acquire(&lease, owner, token, now_ms()))
            return failure(id, 423, "Control is held by another terminal; wait or release the owner");
        result = cJSON_CreateObject();
        cJSON_AddStringToObject(result, "lease_token", token);
        cJSON_AddNumberToObject(result, "ttl_ms", 15000);
        record("Control acquired");
    } else if (!strcmp(m, "control.renew")) {
        if (!authorized(p))
            return failure(id, 423, "Control lease expired; acquire again");
        lease.expires_ms = now_ms() + 15000;
        result = cJSON_CreateObject();
        cJSON_AddNumberToObject(result, "ttl_ms", 15000);
    } else if (!strcmp(m, "control.release")) {
        if(probe.stream_active)return failure(id,409,"Close the native byte stream before releasing control");
        if (!lease_release(&lease, str(p, "lease_token"), now_ms()))
            return failure(id, 423, "Cannot release this lease while busy or owned by another terminal");
        result = cJSON_CreateObject();
        record("Control released");
    } else if (!strcmp(m, "scan_wifi")) {
        if (!authorized(p))
            return failure(id, 423, "Acquire control before radio scanning");
        network_status_t n;
        network_snapshot(&n);
        if (!strcmp(n.actual, "AP"))
            return failure(id, 409, "Choose AP+STA and apply before scanning from AP-only mode");
        wifi_scan_config_t scan = {0};
        if (esp_wifi_scan_start(&scan, true) != ESP_OK)
            return failure(id, 409, "Scan unavailable while connecting; retry later");
        wifi_ap_record_t aps[16];
        uint16_t count = 16;
        if (esp_wifi_scan_get_ap_records(&count, aps) != ESP_OK)
            return failure(id, 500, "Scan failed");
        result = cJSON_CreateArray();
        for (unsigned i = 0; i < count; i++) {
            if (!aps[i].ssid[0])
                continue;
            cJSON *ap = cJSON_CreateObject();
            cJSON_AddStringToObject(ap, "ssid", (char *)aps[i].ssid);
            cJSON_AddNumberToObject(ap, "rssi", aps[i].rssi);
            cJSON_AddStringToObject(ap, "auth", aps[i].authmode == WIFI_AUTH_OPEN ? "OPEN" : "WPA2/WPA3");
            cJSON_AddItemToArray(result, ap);
        }
    } else if (!strcmp(m, "set_config")) {
        if (!authorized(p))
            return failure(id, 423, "Acquire control before changing settings");
        node_settings_t next;
        snapshot(&next);
        char change[65] = {0};
        if (!string_field(p, "change_id", change, sizeof(change), true) || !change[0])
            return failure(id, 400, "Missing change_id");
        if (!strcmp(change, next.last_change_id))
            result = config_json();
        else {
            const cJSON *revision = cJSON_GetObjectItemCaseSensitive(p, "expected_revision");
            if (!cJSON_IsNumber(revision) || revision->valuedouble != next.revision)
                return failure(id, 409, "Configuration changed; reload before saving");
            if (!string_field(p, "node_name", next.node_name, sizeof(next.node_name), true) ||
                !next.node_name[0] || !string_field(p, "wifi_ssid", next.ssid, sizeof(next.ssid), true) ||
                !string_field(p, "wifi_password", next.password, sizeof(next.password), false) ||
                !password_valid(next.password, false) ||
                !string_field(p, "network_mode", next.network_mode, sizeof(next.network_mode), true) ||
                !mode_valid(next.network_mode) ||
                !string_field(p, "ap_ssid", next.ap_ssid, sizeof(next.ap_ssid), true) || !next.ap_ssid[0] ||
                !string_field(p, "ap_password", next.ap_password, sizeof(next.ap_password), false) ||
                !password_valid(next.ap_password, true) ||
                !string_field(p, "gateway_url", next.gateway_url, sizeof(next.gateway_url), true) ||
                !center_url_valid(next.gateway_url) ||
                !string_field(p, "bench_id", next.bench_id, sizeof(next.bench_id), true) ||
                !string_field(p, "relay_token", next.relay_token, sizeof(next.relay_token), false))
                return failure(id, 400, "Invalid mode, credentials or field length");
            const cJSON *enabled = cJSON_GetObjectItemCaseSensitive(p, "gateway_enabled");
            if (!cJSON_IsBool(enabled))
                return failure(id, 400, "gateway_enabled must be a boolean");
            next.gateway_enabled = cJSON_IsTrue(enabled);
            if (next.gateway_enabled && (!next.gateway_url[0] || !next.bench_id[0] || !next.relay_token[0]))
                return failure(id, 400, "Center address, bench ID and token are required");
            strcpy(next.last_change_id, change);
            next.revision++;
            lease.busy = true;
            esp_err_t err = persist(&next);
            lease.busy = false;
            if (err != ESP_OK)
                return failure(id, 503, "Save outcome uncertain; reload before retrying");
            result = config_json();
            record("Configuration saved; apply network to activate changes");
        }
    } else if (!strcmp(m, "apply_network") || !strcmp(m, "connect_wifi")) {
        if (!authorized(p) || lease.busy)
            return failure(id, 423, "Acquire control and wait for the current operation");
        node_settings_t c;
        snapshot(&c);
        if (!strcmp(c.network_mode, "STA") && !c.ssid[0])
            return failure(id, 400, "STA mode requires a saved SSID");
        if (network_schedule(&c) != ESP_OK)
            return failure(id, 503, "Network apply queue unavailable");
        center_configure(&c);
        result = cJSON_CreateObject();
        cJSON_AddBoolToObject(result, "accepted", true);
        cJSON_AddNumberToObject(result, "apply_after_ms", 1500);
        record("Network change scheduled; reconnect if needed");
    } else if (!strcmp(m,"probe.metrics.reset")||!strcmp(m,"probe.metrics.snapshot")) {
        if(!authorized(p)||!probe.stream_active||probe.dirty||strcmp(probe.controller,lease.token))
            return failure(id,423,"Own a healthy native stream before USB measurements");
        if(!strcmp(m,"probe.metrics.reset"))v4_backend_metrics_reset();
        v4_backend_status_t measured;v4_backend_snapshot(&measured);result=cJSON_CreateObject();
        cJSON_AddNumberToObject(result,"rx_bytes",measured.measure_rx_bytes);
        cJSON_AddNumberToObject(result,"tx_bytes",measured.measure_tx_bytes);
        cJSON_AddNumberToObject(result,"start_us",measured.measure_start_us);
        cJSON_AddNumberToObject(result,"tx_start_us",measured.measure_tx_start_us);
        cJSON_AddNumberToObject(result,"first_rx_us",measured.measure_first_rx_us);
        cJSON_AddNumberToObject(result,"last_rx_us",measured.measure_last_rx_us);
        cJSON_AddNumberToObject(result,"rx_pending",measured.rx_pending);
        cJSON_AddNumberToObject(result,"rx_peak",measured.rx_peak);
        cJSON_AddNumberToObject(result,"rx_capacity",measured.rx_capacity);
        cJSON_AddNumberToObject(result,"rx_overflows",measured.rx_overflows);
    } else if (!strncmp(m,"firmware.",9)) {
        if(strcmp(m,"firmware.status")&&!authorized(p))return failure(id,423,"Acquire control before firmware update");
        if(!strcmp(m,"firmware.begin")&&(probe.stream_active||lease.busy||v4_storage_upload_active()))
            return failure(id,423,"Close native V4 sessions and file uploads before node firmware update");
        int code=500;const char *message="Firmware update rejected";
        result=firmware_update_rpc(m,p,lease.token,&code,&message);
        if(!result)return failure(id,code,message);
    } else if (!strncmp(m,"probe.files.",12)) {
        if(!authorized(p))return failure(id,423,"Acquire control before V4 file delivery");
        int code=500;const char *message="File delivery failed";
        lease.busy=true;result=v4_storage_rpc(m,p,lease.token,&code,&message);
        /* A synchronous disk commit is active ownership, even if it outlasts
         * the idle lease. Leave a full cleanup window after it returns. */
        lease.expires_ms=now_ms()+15000;lease.busy=false;
        if(!result)return failure(id,code,message);
    } else if (!strncmp(m,"probe.stream.",13)) {
        if(!authorized(p))return failure(id,423,"Acquire control before native byte transport");
        probe_stream_op_t op;
        if(!strcmp(m,"probe.stream.open"))op=PROBE_STREAM_OPEN;
        else if(!strcmp(m,"probe.stream.read"))op=PROBE_STREAM_READ;
        else if(!strcmp(m,"probe.stream.write"))op=PROBE_STREAM_WRITE;
        else if(!strcmp(m,"probe.stream.close"))op=PROBE_STREAM_CLOSE;
        else if(!strcmp(m,"probe.stream.abort")){
            if(probe.stream_active&&strcmp(probe.controller,lease.token)==0)probe.dirty=true;
            return failure(id,504,"Native protocol state unknown; quarantined without injecting stop bytes");
        }
        else return failure(id,404,"Unsupported native stream operation");
        const cJSON *seq=cJSON_GetObjectItemCaseSensitive(p,"sequence"),*gen=cJSON_GetObjectItemCaseSensitive(p,"generation");
        if(!cJSON_IsNumber(seq)||seq->valuedouble<1||seq->valuedouble>4294967295.0||seq->valuedouble!=(uint32_t)seq->valuedouble||
           !cJSON_IsNumber(gen)||gen->valuedouble<0||gen->valuedouble>4294967295.0||gen->valuedouble!=(uint32_t)gen->valuedouble)
            return failure(id,400,"Current generation and monotonic sequence required");
        uint8_t *input=stream_workspace->input,*output=stream_workspace->output;size_t bytes=0,count=0;
        const char *encoded=str(p,"request_base64");
        if(op==PROBE_STREAM_WRITE&&(!encoded||mbedtls_base64_decode(input,PROBE_PAYLOAD_MAX,&bytes,(const uint8_t*)encoded,strlen(encoded))||!bytes))
            return failure(id,400,"Bounded binary payload required");
        if(op!=PROBE_STREAM_WRITE&&encoded)return failure(id,400,"Payload only permitted for stream write");
        size_t capacity=PROBE_PAYLOAD_MAX; /* Preserve the old default. */
        const cJSON *limit=cJSON_GetObjectItemCaseSensitive(p,"max_bytes");
        if(limit){
            if(op!=PROBE_STREAM_READ||!cJSON_IsNumber(limit)||limit->valuedouble<1||limit->valuedouble>PROBE_READ_MAX||limit->valuedouble!=(unsigned)limit->valuedouble)
                return failure(id,400,"Read limit must contain1..32768 bytes");
            capacity=(size_t)limit->valuedouble;
        }
        lease.busy=true;
        probe_result_t rc=probe_transport_stream(&probe,lease.token,(uint32_t)seq->valuedouble,(uint32_t)gen->valuedouble,op,input,bytes,output,capacity,&count);
        lease.busy=false;
        if(rc!=PROBE_OK)return failure(id,rc==PROBE_OUTCOME_UNKNOWN?504:409,rc==PROBE_OUTCOME_UNKNOWN?
            "Native stream outcome unknown; quarantined, no replay":"Stream state, generation or sequence rejected; no replay");
        unsigned char *encoded_reply=stream_workspace->encoded;size_t length=0;
        /* mbedTLS requires capacity for its terminating NUL as well as the
         * encoded bytes. The PSRAM workspace already includes that byte. */
        if(mbedtls_base64_encode(encoded_reply,sizeof stream_workspace->encoded,&length,output,count))return failure(id,500,"Native response encoding failed; outcome unknown");
        encoded_reply[length]=0;
        result=cJSON_CreateObject();cJSON_AddStringToObject(result,"reply_base64",(char*)encoded_reply);
        cJSON_AddNumberToObject(result,"generation",probe.generation);cJSON_AddNumberToObject(result,"accepted_bytes",bytes);
        cJSON_AddBoolToObject(result,"stream_active",probe.stream_active);
    } else if (!strcmp(m, "probe.exchange")) {
        if (!authorized(p))
            return failure(id, 423, "Acquire control before probe exchange");
        const char *encoded = str(p, "request_base64");
        const cJSON *seq = cJSON_GetObjectItemCaseSensitive(p, "sequence");
        if (!encoded || !cJSON_IsNumber(seq) || seq->valuedouble < 1 || seq->valuedouble > 4294967295.0 ||
            seq->valuedouble != (uint32_t)seq->valuedouble)
            return failure(id, 400, "A monotonic sequence and bounded base64 payload are required");
        uint8_t *request_bytes=stream_workspace->input,*reply_bytes=stream_workspace->output;
        size_t in_size = 0, out_size = 0;
        if (mbedtls_base64_decode(request_bytes, PROBE_PAYLOAD_MAX, &in_size, (uint8_t *)encoded,
                                  strlen(encoded)) ||
            !in_size)
            return failure(id, 400, "Invalid bounded base64 payload");
        const cJSON *generation=cJSON_GetObjectItemCaseSensitive(p,"generation");
        if(probe.ready&&(!cJSON_IsNumber(generation)||generation->valuedouble<0||
           generation->valuedouble>4294967295.0||generation->valuedouble!=(uint32_t)generation->valuedouble))
            return failure(id,409,"Read current V4 generation before sending; no bytes sent");
        lease.busy = true;
        probe_result_t rc =
            probe_transport_exchange(&probe, lease.token, (uint32_t)seq->valuedouble, cJSON_IsNumber(generation)?(uint32_t)generation->valuedouble:0, request_bytes, in_size,
                                     reply_bytes, PROBE_PAYLOAD_MAX, &out_size, 2000);
        lease.busy = false;
        if (rc != PROBE_OK)
            return failure(id,
                           rc == PROBE_NOT_READY         ? 409
                           : rc == PROBE_OUTCOME_UNKNOWN ? 504
                                                         : 409,
                           rc == PROBE_NOT_READY ? "V4 backend unavailable; no USB bytes sent"
                           : rc == PROBE_OUTCOME_UNKNOWN
                               ? "Outcome unknown; transport quarantined, do not replay"
                               : rc == PROBE_STALE ? "V4 generation changed; no bytes sent, inspect before a new request"
                               : "Invalid or duplicate probe request; not replayed");
        unsigned char *text=stream_workspace->encoded;
        size_t written = 0;
        mbedtls_base64_encode(text, sizeof stream_workspace->encoded - 1, &written, reply_bytes, out_size);
        text[written] = 0;
        result = cJSON_CreateObject();
        cJSON_AddStringToObject(result, "reply_base64", (char *)text);
        cJSON_AddNumberToObject(result, "generation", probe.generation);
    } else if (!strncmp(m, "probe.", 6))
        return failure(id, 409, "Mklink operations blocked until V4 USB transport compatibility is verified");
    else
        return failure(id, 404, "Unsupported method");
    cJSON *reply = cJSON_CreateObject();
    cJSON_AddNumberToObject(reply, "v", 1);
    cJSON_AddItemToObject(reply, "id", cJSON_Duplicate(id, true));
    cJSON_AddBoolToObject(reply, "ok", true);
    cJSON_AddItemToObject(reply, "data", result);
    return reply;
}
static char *process(const char *body, bool serial) {
    cJSON *request = strstr(body, "\\u0000") ? NULL : cJSON_ParseWithOpts(body, NULL, true);
    xSemaphoreTake(rpc_lock, portMAX_DELAY);
    cJSON *reply = dispatch(request, serial);
    xSemaphoreGive(rpc_lock);
    char *raw = cJSON_PrintUnformatted(reply);
    cJSON_Delete(reply);
    cJSON_Delete(request);
    return raw;
}
static void owner_watchdog(void *arg){
    (void)arg;
    for(;;){
        if(xSemaphoreTake(rpc_lock,0)==pdTRUE){
            lease_expire(&lease,now_ms());
            probe_transport_reconcile_owner(&probe,lease.owner[0]?lease.token:NULL);
            v4_storage_reconcile_owner(lease.owner[0]?lease.token:NULL);
            xSemaphoreGive(rpc_lock);
        }
        vTaskDelay(pdMS_TO_TICKS(250));
    }
}
void config_button_action(int action) {
    if (xSemaphoreTake(rpc_lock, 0) != pdTRUE)
        return;
    lease_expire(&lease, now_ms());
    network_status_t n;
    network_snapshot(&n);
    if (lease.owner[0] || lease.busy || n.switching || firmware_update_busy()) {
        board_controls_hint();
        record("BOOT switch refused: control held or operation busy");
        xSemaphoreGive(rpc_lock);
        return;
    }
    node_settings_t transient;
    snapshot(&transient);
    if (action == BUTTON_RECOVER_AP || strcmp(n.actual, "AP"))
        strcpy(transient.network_mode, "AP");
    else if (transient.ssid[0])
        strcpy(transient.network_mode, "STA");
    board_controls_hint();
    network_schedule(&transient);
    record("BOOT temporary mode switch; saved preference retained");
    xSemaphoreGive(rpc_lock);
}
char *config_ble_rpc(const char *body) { return process(body, false); }
bool config_bind_probe(const probe_descriptor_t *d, const probe_backend_t *backend) {
    xSemaphoreTake(rpc_lock, portMAX_DELAY);
    bool ready = probe_transport_bind(&probe, d, backend);
    xSemaphoreGive(rpc_lock);
    return ready;
}
void config_unbind_probe(void) {
    xSemaphoreTake(rpc_lock, portMAX_DELAY);
    probe_transport_invalidate(&probe);
    xSemaphoreGive(rpc_lock);
}
static void serial_task(void *arg) {
    (void)arg;
    char line[4096];
    size_t used = 0;
    bool overflow = false;
    setvbuf(stdin, NULL, _IONBF, 0);
    for (;;) {
        int c = getchar();
        if (c == EOF) {
            clearerr(stdin);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (c == '\r')
            continue;
        if (c == '\n') {
            if (!overflow && used > 7 && !memchr(line, 0, used)) {
                line[used] = 0;
                if (!strncmp(line, "@MKCFG ", 7)) {
                    char *reply = process(line + 7, true);
                    if (reply) {
                        flockfile(stdout);
                        printf("@MKCFG %s\n", reply);
                        fflush(stdout);
                        funlockfile(stdout);
                        free(reply);
                    }
                }
            }
            used = 0;
            overflow = false;
        } else if (used < sizeof(line) - 1)
            line[used++] = (char)c;
        else
            overflow = true;
    }
}
static esp_err_t http_rpc(httpd_req_t *req) {
    char auth[64];
    node_settings_t c;
    snapshot(&c);
    bool valid = false;
    if (httpd_req_get_hdr_value_str(req, "Authorization", auth, sizeof(auth)) == ESP_OK &&
        strlen(auth) == 39 && !strncmp(auth, "Bearer ", 7)) {
        unsigned diff = 0;
        for (unsigned i = 0; i < 32; i++)
            diff |= (unsigned char)auth[i + 7] ^ (unsigned char)c.token[i];
        valid = diff == 0;
    }
    if (!valid) {
        httpd_resp_set_status(req, "401 Unauthorized");
        return httpd_resp_sendstr(req, "Unauthorized");
    }
    if (req->content_len <= 0 || req->content_len >= 4096) {
        httpd_resp_set_status(req, "413 Payload Too Large");
        return httpd_resp_sendstr(req, "Request too large");
    }
    char *body = malloc(req->content_len + 1);
    if (!body)
        return ESP_ERR_NO_MEM;
    size_t used = 0;
    while (used < (size_t)req->content_len) {
        int count = httpd_req_recv(req, body + used, req->content_len - used);
        if (count <= 0) {
            free(body);
            return ESP_FAIL;
        }
        used += count;
    }
    body[used] = 0;
    if (memchr(body, 0, used)) {
        free(body);
        httpd_resp_set_status(req, "400 Bad Request");
        return httpd_resp_sendstr(req, "Invalid JSON");
    }
    char *reply = process(body, false);
    free(body);
    if (!reply)
        return ESP_ERR_NO_MEM;
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    esp_err_t err = httpd_resp_sendstr(req, reply);
    free(reply);
    return err;
}
extern const unsigned char web_start[] asm("_binary_device_html_start");
extern const unsigned char web_end[] asm("_binary_device_html_end");
static esp_err_t web_page(httpd_req_t *req) {
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_hdr(req, "X-Content-Type-Options", "nosniff");
    httpd_resp_set_hdr(req, "Content-Security-Policy",
                       "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                       "connect-src 'self'; img-src data:; base-uri 'none'; frame-ancestors 'none'");
    return httpd_resp_send(req, (char *)web_start, web_end - web_start - 1);
}
static esp_err_t health(httpd_req_t *req) {
    char text[96];
    snprintf(text, sizeof(text), "{\"device_id\":\"%s\",\"firmware\":\"%s\",\"protocol\":1}", device_id,esp_app_get_description()->version);
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_sendstr(req, text);
}
static esp_err_t open_http_socket(httpd_handle_t server,int socket_fd){
    (void)server;
    /* HTTP headers and small RPC replies must not wait for a delayed ACK
     * between the server's separate header/body writes. IDF open_fn runs
     * after accept and before reading application data. */
    int enabled=1;
    return setsockopt(socket_fd,IPPROTO_TCP,TCP_NODELAY,&enabled,sizeof enabled)==0?ESP_OK:ESP_FAIL;
}
static bool terminated(const node_settings_t *c) {
    return memchr(c->node_name, 0, sizeof(c->node_name)) && memchr(c->ssid, 0, sizeof(c->ssid)) &&
           memchr(c->password, 0, sizeof(c->password)) && memchr(c->gateway_url, 0, sizeof(c->gateway_url)) &&
           memchr(c->token, 0, sizeof(c->token)) && memchr(c->last_change_id, 0, sizeof(c->last_change_id)) &&
           memchr(c->network_mode, 0, sizeof(c->network_mode)) && memchr(c->ap_ssid, 0, sizeof(c->ap_ssid)) &&
           memchr(c->ap_password, 0, sizeof(c->ap_password)) && memchr(c->bench_id, 0, sizeof(c->bench_id)) &&
           memchr(c->relay_token, 0, sizeof(c->relay_token));
}
esp_err_t config_service_start(void) {
    stream_workspace=heap_caps_malloc(sizeof *stream_workspace,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!stream_workspace)return ESP_ERR_NO_MEM;
    config_lock = xSemaphoreCreateMutex();
    rpc_lock = xSemaphoreCreateMutex();
    if (!config_lock || !rpc_lock)
        return ESP_ERR_NO_MEM;
    ESP_RETURN_ON_ERROR(nvs_flash_init(), "config", "NVS initialization failed; no automatic erase");
    ESP_RETURN_ON_ERROR(firmware_update_init(),"config","OTA initialization failed");
    ESP_RETURN_ON_ERROR(nvs_open("mkconfig", NVS_READWRITE, &storage), "config", "NVS open failed");
    uint8_t mac[6];
    ESP_RETURN_ON_ERROR(esp_read_mac(mac, ESP_MAC_WIFI_STA), "config", "MAC failed");
    snprintf(device_id, sizeof(device_id), "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3], mac[4],
             mac[5]);
    size_t size = 0;
    esp_err_t loaded = nvs_get_blob(storage, "settings", NULL, &size);
    if (loaded == ESP_ERR_NVS_NOT_FOUND) {
        memset(&settings, 0, sizeof(settings));
        settings.magic = NODE_SETTINGS_MAGIC;
        settings.revision = 1;
        strcpy(settings.node_name, "Mklink Remote");
        strcpy(settings.network_mode, "AP");
    } else if (loaded == ESP_OK && size == sizeof(settings)) {
        ESP_RETURN_ON_ERROR(nvs_get_blob(storage, "settings", &settings, &size), "config",
                            "Settings read failed");
        if (settings.magic != NODE_SETTINGS_MAGIC || !terminated(&settings) ||
            !mode_valid(settings.network_mode) || !password_valid(settings.ap_password, true))
            return ESP_ERR_INVALID_STATE;
    } else if (loaded == ESP_OK && size == offsetof(node_settings_t, network_mode)) {
        ESP_RETURN_ON_ERROR(nvs_get_blob(storage, "settings", &settings, &size), "config",
                            "Legacy settings read failed");
        if (settings.magic != 0x53474331u || !memchr(settings.node_name, 0, sizeof(settings.node_name)) ||
            !memchr(settings.ssid, 0, sizeof(settings.ssid)) ||
            !memchr(settings.password, 0, sizeof(settings.password)) ||
            !memchr(settings.gateway_url, 0, sizeof(settings.gateway_url)) ||
            !memchr(settings.token, 0, sizeof(settings.token)) ||
            !memchr(settings.last_change_id, 0, sizeof(settings.last_change_id)) ||
            !password_valid(settings.password, false))
            return ESP_ERR_INVALID_STATE;
        settings.magic = NODE_SETTINGS_MAGIC;
        strcpy(settings.network_mode, settings.ssid[0] ? "STA" : "AP");
    } else
        return ESP_ERR_INVALID_STATE;
    if (!settings.token[0])
        random_hex(settings.token, 16);
    if (!settings.ap_ssid[0])
        snprintf(settings.ap_ssid, sizeof(settings.ap_ssid), "MklinkRemote-%02X%02X%02X", mac[3], mac[4],
                 mac[5]);
    if (!settings.ap_password[0])
        random_hex(settings.ap_password, 8);
    if (!settings.bench_id[0])
        snprintf(settings.bench_id, sizeof(settings.bench_id), "s3-%s", device_id);
    ESP_RETURN_ON_ERROR(persist(&settings), "config", "Settings initialization failed");
    ESP_RETURN_ON_ERROR(network_start(&settings), "config", "Network start failed");
    ESP_RETURN_ON_ERROR(center_start(), "config", "Center task failed");
    center_configure(&settings);
    httpd_config_t server_config = HTTPD_DEFAULT_CONFIG();
    server_config.open_fn=open_http_socket;
    server_config.server_port = 80;
    server_config.stack_size = 12288;
    server_config.max_uri_handlers = 4;
    server_config.lru_purge_enable = true;
    httpd_handle_t server = NULL;
    ESP_RETURN_ON_ERROR(httpd_start(&server, &server_config), "config", "HTTP start failed");
    httpd_uri_t rpc = {.uri = "/api/v1/rpc", .method = HTTP_POST, .handler = http_rpc},
                web = {.uri = "/", .method = HTTP_GET, .handler = web_page},
                health_uri = {.uri = "/health", .method = HTTP_GET, .handler = health};
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &rpc), "config", "RPC route failed");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &web), "config", "Web route failed");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &health_uri), "config", "Health route failed");
    if (xTaskCreate(serial_task, "config_serial", 12288, NULL, 3, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;
    if(xTaskCreate(owner_watchdog,"probe_owner",3072,NULL,2,NULL)!=pdPASS)return ESP_ERR_NO_MEM;
    ESP_RETURN_ON_ERROR(board_controls_start(), "config", "BOOT/RGB initialization failed");
    char ble_name[25];
    snprintf(ble_name, sizeof(ble_name), "MklinkRemote-%s", device_id + 6);
    for (unsigned i = 13; ble_name[i]; i++)
        ble_name[i] = toupper((unsigned char)ble_name[i]);
    ESP_RETURN_ON_ERROR(ble_config_start(ble_name), "config", "BLE configuration interface failed");
    record("CONFIG_READY protocol=1 UART0=115200 HTTP=80; credentials available through USB pairing");
    return ESP_OK;
}
