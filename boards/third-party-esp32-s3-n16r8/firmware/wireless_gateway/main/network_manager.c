#include "network_manager.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include <stdio.h>
#include <string.h>
static SemaphoreHandle_t lock;
static QueueHandle_t queue;
static network_status_t state;
static node_settings_t current;
static esp_netif_t *ap_netif;
static unsigned retries;
static bool started, changing;
static void take(void) { xSemaphoreTake(lock, portMAX_DELAY); }
static void give(void) { xSemaphoreGive(lock); }
void network_snapshot(network_status_t *out) {
    take();
    *out = state;
    give();
    wifi_ap_record_t ap = {0};
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        out->rssi = ap.rssi;
        snprintf(out->sta_ssid, sizeof(out->sta_ssid), "%s", (char *)ap.ssid);
    }
}
static esp_err_t configure(const node_settings_t *settings) {
    take();
    changing = true;
    state.switching = true;
    current = *settings;
    give();
    if (started) {
        esp_wifi_stop();
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    const char *actual =
        !settings->ssid[0] && strcmp(settings->network_mode, "AP") == 0 ? "AP" : settings->network_mode;
    if (!settings->ssid[0] && strcmp(actual, "STA") == 0)
        actual = "AP";
    wifi_mode_t mode = strcmp(actual, "AP") == 0    ? WIFI_MODE_AP
                       : strcmp(actual, "STA") == 0 ? WIFI_MODE_STA
                                                    : WIFI_MODE_APSTA;
    esp_err_t err = esp_wifi_set_mode(mode);
    if (err == ESP_OK && mode != WIFI_MODE_AP) {
        wifi_config_t sta = {0};
        memcpy(sta.sta.ssid, settings->ssid, strlen(settings->ssid));
        memcpy(sta.sta.password, settings->password, strlen(settings->password));
        err = esp_wifi_set_config(WIFI_IF_STA, &sta);
    }
    if (err == ESP_OK && mode != WIFI_MODE_STA) {
        wifi_config_t ap = {0};
        memcpy(ap.ap.ssid, settings->ap_ssid, strlen(settings->ap_ssid));
        ap.ap.ssid_len = strlen(settings->ap_ssid);
        memcpy(ap.ap.password, settings->ap_password, strlen(settings->ap_password));
        ap.ap.max_connection = 4;
        ap.ap.channel = 6;
        ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
        ap.ap.pmf_cfg.capable = true;
        err = esp_wifi_set_config(WIFI_IF_AP, &ap);
    }
    take();
    snprintf(state.requested, sizeof(state.requested), "%s", settings->network_mode);
    snprintf(state.actual, sizeof(state.actual), "%s", actual);
    snprintf(state.ap_ssid, sizeof(state.ap_ssid), "%s", settings->ap_ssid);
    snprintf(state.sta_ssid, sizeof(state.sta_ssid), "%s", settings->ssid);
    state.ap_active = false;
    state.ap_clients = 0;
    state.ip[0] = 0;
    state.ap_ip[0] = 0;
    state.error[0] = 0;
    snprintf(state.sta_state, sizeof(state.sta_state), "%s",
             mode == WIFI_MODE_AP ? "unconfigured"
             : settings->ssid[0]  ? "connecting"
                                  : "unconfigured");
    retries = 0;
    changing = false;
    give();
    if (err == ESP_OK)
        err = esp_wifi_start();
    take();
    state.switching = false;
    if (err != ESP_OK)
        snprintf(state.error, sizeof(state.error), "Network error: %s", esp_err_to_name(err));
    give();
    started = err == ESP_OK;
    return err;
}
static void network_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        take();
        bool connect = current.ssid[0] && !changing;
        give();
        if (connect)
            esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *event = data;
        take();
        if (changing) {
            give();
            return;
        }
        state.ip[0] = 0;
        bool retry = current.ssid[0] && retries++ < 3;
        snprintf(state.sta_state, sizeof(state.sta_state), "%s", retry ? "connecting" : "disconnected");
        snprintf(state.error, sizeof(state.error), "Wi-Fi disconnected (reason %u)", event->reason);
        bool fallback = !retry && strcmp(state.actual, "STA") == 0;
        // This callback runs on sys_evt. Keep the large settings snapshot out of
        // its stack; handlers on the default event loop execute serially.
        static node_settings_t recovery;
        recovery = current;
        if (fallback)
            strcpy(recovery.network_mode, "AP+STA");
        give();
        if (retry)
            esp_wifi_connect();
        else if (fallback)
            xQueueOverwrite(queue, &recovery);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        esp_netif_ip_info_t ap_info;
        if (esp_netif_get_ip_info(ap_netif, &ap_info) == ESP_OK &&
            (event->ip_info.ip.addr & ap_info.netmask.addr) == (ap_info.ip.addr & ap_info.netmask.addr)) {
            esp_netif_dhcps_stop(ap_netif);
            esp_netif_str_to_ip4("192.168.6.1", &ap_info.ip);
            ap_info.gw = ap_info.ip;
            if ((event->ip_info.ip.addr & ap_info.netmask.addr) == (ap_info.ip.addr & ap_info.netmask.addr)) {
                esp_netif_str_to_ip4("192.168.7.1", &ap_info.ip);
                ap_info.gw = ap_info.ip;
            }
            if (esp_netif_set_ip_info(ap_netif, &ap_info) == ESP_OK) {
                esp_netif_dhcps_start(ap_netif);
                esp_wifi_deauth_sta(0);
                take();
                snprintf(state.ap_ip, sizeof(state.ap_ip), IPSTR, IP2STR(&ap_info.ip));
                give();
                ESP_LOGW("network", "AP subnet moved to avoid STA collision; clients must reconnect");
            }
        }
        take();
        snprintf(state.ip, sizeof(state.ip), IPSTR, IP2STR(&event->ip_info.ip));
        strcpy(state.sta_state, "connected");
        state.error[0] = 0;
        retries = 0;
        give();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_START) {
        esp_netif_ip_info_t info;
        esp_netif_get_ip_info(ap_netif, &info);
        take();
        state.ap_active = true;
        snprintf(state.ap_ip, sizeof(state.ap_ip), IPSTR, IP2STR(&info.ip));
        give();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STACONNECTED) {
        take();
        state.ap_clients++;
        give();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STADISCONNECTED) {
        take();
        if (state.ap_clients > 0)
            state.ap_clients--;
        give();
    }
}
static void worker(void *arg) {
    (void)arg;
    node_settings_t next;
    uint64_t last_retry = 0;
    for (;;) {
        if (xQueueReceive(queue, &next, pdMS_TO_TICKS(1000)) == pdTRUE) {
            vTaskDelay(pdMS_TO_TICKS(1500));
            configure(&next);
        } else {
            uint64_t now = esp_timer_get_time() / 1000;
            take();
            bool retry = started && !changing && strcmp(state.actual, "AP") && current.ssid[0] &&
                         !strcmp(state.sta_state, "disconnected") && now - last_retry >= 5000;
            if (retry)
                strcpy(state.sta_state, "connecting");
            give();
            if (retry) {
                last_retry = now;
                if (esp_wifi_connect() != ESP_OK) {
                    take();
                    strcpy(state.sta_state, "disconnected");
                    give();
                }
            }
        }
    }
}
esp_err_t network_schedule(const node_settings_t *settings) {
    take();
    state.switching = true;
    give();
    return xQueueOverwrite(queue, settings) == pdTRUE ? ESP_OK : ESP_FAIL;
}
esp_err_t network_start(const node_settings_t *settings) {
    lock = xSemaphoreCreateMutex();
    queue = xQueueCreate(1, sizeof(node_settings_t));
    if (!lock || !queue)
        return ESP_ERR_NO_MEM;
    esp_err_t err = esp_netif_init();
    if (err != ESP_OK)
        return err;
    err = esp_event_loop_create_default();
    if (err != ESP_OK)
        return err;
    if (!esp_netif_create_default_wifi_sta())
        return ESP_ERR_NO_MEM;
    ap_netif = esp_netif_create_default_wifi_ap();
    if (!ap_netif)
        return ESP_ERR_NO_MEM;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    if ((err = esp_wifi_init(&init)) != ESP_OK)
        return err;
    /* This USB-powered debug gateway prioritizes latency and sustained traffic;
     * do not wait for DTIM windows between native target RPCs. */
    if ((err = esp_wifi_set_ps(WIFI_PS_NONE)) != ESP_OK)
        return err;
    if ((err = esp_wifi_set_storage(WIFI_STORAGE_RAM)) != ESP_OK)
        return err;
    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, network_event, NULL);
    esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, network_event, NULL);
    esp_sntp_config_t time_config = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
    time_config.start = false;
    esp_netif_sntp_init(&time_config);
    esp_netif_sntp_start();
    if (xTaskCreate(worker, "network_apply", 6144, NULL, 3, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;
    return configure(settings);
}
