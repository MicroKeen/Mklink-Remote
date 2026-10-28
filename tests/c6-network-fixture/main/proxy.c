/* One bounded TCP endpoint (port 8910) bridges S3 Wi-Fi bytes to the host's
 * isolated loopback HIL gateway over USB. It never routes the PC's Wi-Fi.
 * All proxy payloads are test credentials and must not be persisted raw. */
#include "proxy.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "mbedtls/base64.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static int listener = -1, peer = -1;
static unsigned generation;
static SemaphoreHandle_t lock;
static void emit(const char *type, unsigned id, const uint8_t *data, size_t length) {
    char encoded[1400];
    size_t n = 0;
    if (length)
        mbedtls_base64_encode((uint8_t *)encoded, sizeof(encoded), &n, data, length);
    encoded[n] = 0;
    cJSON *j = cJSON_CreateObject();
    cJSON_AddStringToObject(j, "type", type);
    cJSON_AddNumberToObject(j, "connection", id);
    if (length)
        cJSON_AddStringToObject(j, "data", encoded);
    char *raw = cJSON_PrintUnformatted(j);
    if (raw) {
        flockfile(stdout);
        printf("@MKTEST_EVENT %s\n", raw);
        fflush(stdout);
        funlockfile(stdout);
        free(raw);
    }
    cJSON_Delete(j);
}
static void task(void *arg) {
    (void)arg;
    uint8_t data[768];
    for (;;) {
        struct sockaddr_in remote;
        socklen_t length = sizeof(remote);
        int client = accept(listener, (struct sockaddr *)&remote, &length);
        if (client < 0) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        xSemaphoreTake(lock, portMAX_DELAY);
        peer = client;
        unsigned id = ++generation;
        xSemaphoreGive(lock);
        emit("proxy.open", id, NULL, 0);
        for (;;) {
            int n = recv(client, data, sizeof(data), 0);
            if (n <= 0)
                break;
            emit("proxy.data", id, data, n);
        }
        xSemaphoreTake(lock, portMAX_DELAY);
        if (peer == client)
            peer = -1;
        xSemaphoreGive(lock);
        close(client);
        emit("proxy.close", id, NULL, 0);
    }
}
cJSON *fixture_proxy(const char *method, const cJSON *params, const char **error) {
    if (!lock)
        lock = xSemaphoreCreateMutex();
    if (!lock) {
        *error = "Proxy lock allocation failed";
        return NULL;
    }
    if (!strcmp(method, "proxy.start")) {
        if (listener < 0) {
            listener = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
            int reuse = 1;
            setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
            struct sockaddr_in addr = {
                .sin_family = AF_INET, .sin_port = htons(8910), .sin_addr.s_addr = htonl(INADDR_ANY)};
            if (listener < 0 || bind(listener, (struct sockaddr *)&addr, sizeof(addr)) < 0 ||
                listen(listener, 1) < 0) {
                if (listener >= 0)
                    close(listener);
                listener = -1;
                *error = "Proxy listen failed";
                return NULL;
            }
            if (xTaskCreate(task, "usb_tcp_proxy", 4096, NULL, 3, NULL) != pdPASS) {
                close(listener);
                listener = -1;
                *error = "Proxy task failed";
                return NULL;
            }
        }
        cJSON *j = cJSON_CreateObject();
        cJSON_AddNumberToObject(j, "port", 8910);
        return j;
    }
    if (!strcmp(method, "proxy.write") || !strcmp(method, "proxy.close")) {
        cJSON *id = cJSON_GetObjectItemCaseSensitive(params, "connection");
        if (!cJSON_IsNumber(id)) {
            *error = "Connection ID required";
            return NULL;
        }
        xSemaphoreTake(lock, portMAX_DELAY);
        int fd = peer;
        if (fd < 0 || (unsigned)id->valueint != generation) {
            xSemaphoreGive(lock);
            *error = "Proxy connection changed";
            return NULL;
        }
        int sent = 0;
        if (!strcmp(method, "proxy.close")) {
            shutdown(fd, SHUT_RDWR);
        } else {
            cJSON *text = cJSON_GetObjectItemCaseSensitive(params, "data");
            uint8_t raw[768];
            size_t length = 0;
            if (!cJSON_IsString(text) ||
                mbedtls_base64_decode(raw, sizeof(raw), &length, (uint8_t *)text->valuestring,
                                      strlen(text->valuestring)) != 0) {
                xSemaphoreGive(lock);
                *error = "Invalid bounded proxy frame";
                return NULL;
            }
            struct timeval timeout = {.tv_sec = 3};
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
            while (sent < (int)length) {
                int n = send(fd, raw + sent, length - sent, 0);
                if (n <= 0) {
                    xSemaphoreGive(lock);
                    *error = "Proxy write outcome uncertain; not replayed";
                    return NULL;
                }
                sent += n;
            }
        }
        xSemaphoreGive(lock);
        cJSON *j = cJSON_CreateObject();
        cJSON_AddNumberToObject(j, "written", sent);
        return j;
    }
    *error = "Unknown proxy method";
    return NULL;
}
