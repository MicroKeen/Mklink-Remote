/* Independent Wi-Fi fixture for Waveshare ESP32-C6-Touch-AMOLED-2.16.
 * No display/I2C/audio/power pin writes. USB Serial-JTAG carries all host I/O.
 * The PC never joins or changes a Wi-Fi network. Build only until authorized. */
#include "cJSON.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_transport.h"
#include "esp_transport_tcp.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_heap_caps.h"
#include "lwip/sockets.h"
#include "lwip/tcp.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"
#include "nvs_flash.h"
#include "proxy.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static EventGroupHandle_t flags;
static char ip[16], identity[13];
static bool started;
static esp_netif_t *ap_netif;
static wifi_config_t saved_ap;
static char ap_ip[16] = "192.168.50.1";
static void event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = data;
        snprintf(ip, sizeof(ip), IPSTR, IP2STR(&e->ip_info.ip));
        xEventGroupSetBits(flags, 1);
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ip[0] = 0;
        xEventGroupClearBits(flags, 1);
    }
}
static const char *string(const cJSON *p, const char *name) {
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(p, name);
    return cJSON_IsString(v) ? v->valuestring : "";
}
static void http_cleanup(esp_http_client_handle_t client, esp_transport_handle_t tcp) {
    esp_http_client_cleanup(client);
    /* Custom transports are supplied by the caller, outside the client's list. */
    esp_transport_destroy(tcp);
}
static cJSON *handle(const char *method, const cJSON *p, const char **error) {
    cJSON *result = cJSON_CreateObject();
    if (!strncmp(method, "proxy.", 6)) {
        cJSON_Delete(result);
        return fixture_proxy(method, p, error);
    }
    if (!strcmp(method, "get_status")) {
        cJSON_AddStringToObject(result, "board", "Waveshare ESP32-C6-Touch-AMOLED-2.16");
        cJSON_AddStringToObject(result, "id", identity);
        cJSON_AddStringToObject(result, "ip", ip);
        cJSON_AddStringToObject(result, "fixture", "0.2.4");
        cJSON_AddNumberToObject(result,"free_heap",esp_get_free_heap_size());
        cJSON_AddNumberToObject(result,"minimum_free_heap",esp_get_minimum_free_heap_size());
        cJSON_AddNumberToObject(result,"largest_heap_block",heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
        wifi_ps_type_t power_save;
        if (esp_wifi_get_ps(&power_save) == ESP_OK)
            cJSON_AddStringToObject(result, "wifi_power_save", power_save == WIFI_PS_NONE ? "none" : "modem");
    } else if (!strcmp(method, "wifi.stop")) {
        if (started)
            esp_wifi_stop();
        started = false;
        ip[0] = 0;
        xEventGroupClearBits(flags, 1);
    } else if (!strcmp(method, "ap.start") || !strcmp(method, "sta.join") || !strcmp(method, "apsta.join")) {
        const char *ssid = string(p, "ssid"), *password = string(p, "password");
        bool ap = !strcmp(method, "ap.start"), both = !strcmp(method, "apsta.join");
        if (!ssid[0] || strlen(ssid) > 32 || strlen(password) > 63 || (ap && strlen(password) < 8)) {
            *error = "Invalid SSID/password";
            goto failed;
        }
        if (started) {
            esp_wifi_stop();
            started = false;
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        xEventGroupClearBits(flags, 1);
        ip[0] = 0;
        wifi_config_t c = {0};
        esp_err_t err = esp_wifi_set_mode(ap ? WIFI_MODE_AP : both ? WIFI_MODE_APSTA : WIFI_MODE_STA);
        if (ap) {
            strcpy((char *)c.ap.ssid, ssid);
            c.ap.ssid_len = strlen(ssid);
            strcpy((char *)c.ap.password, password);
            c.ap.authmode = WIFI_AUTH_WPA2_PSK;
            c.ap.max_connection = 4;
            c.ap.channel = 6;
            saved_ap = c;
            const char *requested = string(p, "ap_ip");
            if (!strcmp(requested, "192.168.4.1"))
                strcpy(ap_ip, requested);
            else
                strcpy(ap_ip, "192.168.50.1");
            esp_netif_dhcps_stop(ap_netif);
            esp_netif_ip_info_t info = {0};
            esp_netif_str_to_ip4(ap_ip, &info.ip);
            info.gw = info.ip;
            esp_netif_str_to_ip4("255.255.255.0", &info.netmask);
            esp_netif_set_ip_info(ap_netif, &info);
        } else {
            memcpy(c.sta.ssid, ssid, strlen(ssid));
            memcpy(c.sta.password, password, strlen(password));
        }
        if (err == ESP_OK)
            err = esp_wifi_set_config(ap ? WIFI_IF_AP : WIFI_IF_STA, &c);
        if (err == ESP_OK && both)
            err = esp_wifi_set_config(WIFI_IF_AP, &saved_ap);
        if (err == ESP_OK)
            err = esp_wifi_start();
        if (ap || both)
            esp_netif_dhcps_start(ap_netif);
        started = err == ESP_OK;
        if (err != ESP_OK) {
            *error = "Wi-Fi start failed";
            goto failed;
        }
        if (ap)
            cJSON_AddStringToObject(result, "ip", ap_ip);
        else {
            esp_wifi_connect();
            if (!(xEventGroupWaitBits(flags, 1, pdFALSE, pdFALSE, pdMS_TO_TICKS(30000)) & 1)) {
                *error = "STA join timeout";
                goto failed;
            }
            cJSON_AddStringToObject(result, "ip", ip);
        }
    } else if (!strcmp(method, "http.request")) {
        const char *host = string(p, "host"), *path = string(p, "path"), *verb = string(p, "verb");
        unsigned a, b, c, d;
        char extra;
        if (sscanf(host, "%u.%u.%u.%u%c", &a, &b, &c, &d, &extra) != 4 || a > 255 || b > 255 || c > 255 ||
            d > 255 || !(a == 10 || (a == 192 && b == 168) || (a == 172 && b >= 16 && b <= 31)) ||
            (strcmp(path, "/health") && strcmp(path, "/api/v1/rpc") && strcmp(path, "/"))) {
            *error = "Only private IPv4 S3 health/RPC endpoints are allowed";
            goto failed;
        }
        char url[160];
        snprintf(url, sizeof(url), "http://%s%s", host, path);
        int64_t began=esp_timer_get_time();
        esp_transport_handle_t tcp=esp_transport_tcp_init();
        if(!tcp){*error="TCP transport allocation failed";goto failed;}
        esp_http_client_config_t cfg = {.url = url, .timeout_ms = 10000, .disable_auto_redirect = true, .transport=tcp};
        esp_http_client_handle_t client = esp_http_client_init(&cfg);
        if (!client) {
            esp_transport_destroy(tcp);
            *error = "HTTP allocation failed";
            goto failed;
        }
        const char *body = string(p, "body"), *token = string(p, "token");
        bool post = !strcmp(verb, "POST");
        if (post) {
            esp_http_client_set_method(client, HTTP_METHOD_POST);
            esp_http_client_set_header(client, "Content-Type", "application/json");
        }
        if (token[0]) {
            char auth[64];
            if (strlen(token) != 32) {
                http_cleanup(client,tcp);
                *error = "Invalid management token";
                goto failed;
            }
            snprintf(auth, sizeof(auth), "Bearer %s", token);
            esp_http_client_set_header(client, "Authorization", auth);
        }
        enum { RESPONSE_CAPACITY=65536 };
        char *response=malloc(RESPONSE_CAPACITY);
        if(!response){http_cleanup(client,tcp);*error="HTTP response workspace allocation failed; request not sent";goto failed;}
        esp_err_t err = esp_http_client_open(client, post ? strlen(body) : 0);
        int64_t connected=esp_timer_get_time();
        int one=1;
        if(err==ESP_OK&&setsockopt(esp_transport_get_socket(tcp),IPPROTO_TCP,TCP_NODELAY,&one,sizeof(one)))err=ESP_FAIL;
        if (err == ESP_OK && post && esp_http_client_write(client, body, strlen(body)) != (int)strlen(body))
            err = ESP_FAIL;
        if (err == ESP_OK && cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(p, "summary"))) {
            esp_http_client_fetch_headers(client);
            int code = esp_http_client_get_status_code(client);
            uint8_t block[512], digest[32];
            size_t total = 0;
            mbedtls_sha256_context sha;
            mbedtls_sha256_init(&sha);
            mbedtls_sha256_starts(&sha, 0);
            int n;
            while ((n = esp_http_client_read(client, (char *)block, sizeof(block))) > 0) {
                total += n;
                if (total > 65536) {
                    n = -1;
                    break;
                }
                mbedtls_sha256_update(&sha, block, n);
            }
            mbedtls_sha256_finish(&sha, digest);
            mbedtls_sha256_free(&sha);
            http_cleanup(client,tcp);
            free(response);
            if (n < 0) {
                *error = "HTTP summary read failed";
                goto failed;
            }
            char hex[65];
            for (unsigned i = 0; i < 32; i++)
                snprintf(hex + i * 2, 3, "%02x", digest[i]);
            cJSON_AddNumberToObject(result, "status", code);
            cJSON_AddNumberToObject(result, "bytes", total);
            cJSON_AddStringToObject(result, "sha256", hex);
            return result;
        }
        int count = -1, code = 0;
        if (err == ESP_OK) {
            esp_http_client_fetch_headers(client);
            code = esp_http_client_get_status_code(client);
            count = esp_http_client_read_response(client, response, RESPONSE_CAPACITY - 1);
        }
        int64_t received=esp_timer_get_time();
        http_cleanup(client,tcp);
        if (count < 0 || count >= RESPONSE_CAPACITY - 1) {
            free(response);
            *error = "HTTP read failed or response too large";
            goto failed;
        }
        response[count] = 0;
        cJSON_AddNumberToObject(result, "status", code);
        cJSON_AddStringToObject(result, "body", response);
        free(response);
        cJSON_AddNumberToObject(result,"connect_us",connected-began);
        cJSON_AddNumberToObject(result,"response_us",received-connected);
        cJSON_AddNumberToObject(result,"total_us",esp_timer_get_time()-began);
    } else {
        *error = "Unsupported fixture method";
        goto failed;
    }
    return result;
failed:
    cJSON_Delete(result);
    return NULL;
}
void app_main(void) {
    // The nonblocking ROM console can drop bursts larger than the hardware FIFO.
    // RPC and TCP-proxy frames require an interrupt-driven buffered transport.
    usb_serial_jtag_driver_config_t usb = {.rx_buffer_size = 8192, .tx_buffer_size = 8192};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
    usb_serial_jtag_vfs_use_driver();
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    flags = xEventGroupCreate();
    esp_netif_create_default_wifi_sta();
    ap_netif = esp_netif_create_default_wifi_ap();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    /* USB-powered debug traffic needs prompt replies, not DTIM buffering. */
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, event, NULL);
    esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, event, NULL);
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(identity, sizeof(identity), "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3], mac[4],
             mac[5]);
    setvbuf(stdin, NULL, _IONBF, 0);
    printf("C6_FIXTURE_READY protocol=1\n");
    char *line = malloc(8192);
    if (!line)
        abort();
    size_t used = 0;
    bool overflow = false;
    for (;;) {
        int ch = getchar();
        if (ch == EOF) {
            clearerr(stdin);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (ch == '\r')
            continue;
        if (ch != '\n') {
            if (used < 8191)
                line[used++] = ch;
            else
                overflow = true;
            continue;
        }
        if (!overflow && used > 8 && !memchr(line, 0, used)) {
            line[used] = 0;
            if (!strncmp(line, "@MKTEST ", 8)) {
                cJSON *req = cJSON_ParseWithOpts(line + 8, NULL, true),
                      *id = cJSON_GetObjectItemCaseSensitive(req, "id"),
                      *params = cJSON_GetObjectItemCaseSensitive(req, "params");
                const char *error = NULL;
                cJSON *data = handle(string(req, "method"), params, &error);
                cJSON *reply = cJSON_CreateObject();
                cJSON_AddItemToObject(reply, "id", id ? cJSON_Duplicate(id, true) : cJSON_CreateNull());
                cJSON_AddBoolToObject(reply, "ok", data != NULL);
                if (data)
                    cJSON_AddItemToObject(reply, "data", data);
                else
                    cJSON_AddStringToObject(reply, "error", error ? error : "Invalid request");
                char *raw = cJSON_PrintUnformatted(reply);
                if (raw) {
                    printf("@MKTEST %s\n", raw);
                    fflush(stdout);
                    free(raw);
                }
                cJSON_Delete(reply);
                cJSON_Delete(req);
            }
        }
        used = 0;
        overflow = false;
    }
}
