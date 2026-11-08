#include "http_reply.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include <stdlib.h>

struct http_reply {
    httpd_req_t *request;
    const char *data;
    size_t bytes;
    bool owned;
    uint32_t started_ms;
    http_reply_done_t done;
    void (*receive)(http_reply_t *);
};
static struct http_reply replies[HTTP_REPLY_SLOTS];
static http_reply_status_t status;
static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static QueueHandle_t queue;
static TaskHandle_t workers[HTTP_REPLY_SLOTS];
static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }

static void release(http_reply_t *r, esp_err_t error) {
    unsigned i = (unsigned)(r - replies);
    if (r->request) {
        /* Do not let HTTPD reuse this fd between a failed send and shutdown. */
        if (error != ESP_OK) shutdown(httpd_req_to_sockfd(r->request), SHUT_RDWR);
        esp_err_t completed = httpd_req_async_handler_complete(r->request);
        r->request = NULL;
        if (completed != ESP_OK) {
            portENTER_CRITICAL(&lock);
            status.completion_errors++;
            portEXIT_CRITICAL(&lock);
        }
    }
    if (r->owned) free((void *)r->data);
    if (r->done) r->done(r->started_ms, error);
    uint32_t elapsed = now_ms() - r->started_ms;
    portENTER_CRITICAL(&lock);
    status.slots[i].elapsed_ms = elapsed;
    status.slots[i].error = error;
    status.slots[i].stage = error == ESP_OK ? HTTP_REPLY_DONE : HTTP_REPLY_FAILED;
    status.slots[i].active = false;
    status.active--;
    portEXIT_CRITICAL(&lock);
}

static void send_reply(http_reply_t *r) {
    unsigned i = (unsigned)(r - replies);
    portENTER_CRITICAL(&lock);
    status.slots[i].stage = HTTP_REPLY_SENDING;
    portEXIT_CRITICAL(&lock);
    esp_err_t err = httpd_resp_send(r->request, r->data, r->bytes);
    uint32_t stack = uxTaskGetStackHighWaterMark(NULL);
    portENTER_CRITICAL(&lock);
    status.completed++;
    if (err != ESP_OK) status.send_errors++;
    if (status.completed == 1 || stack < status.stack_min_bytes) status.stack_min_bytes = stack;
    portEXIT_CRITICAL(&lock);
    release(r, err);
}

static void sender(void *arg) {
    (void)arg;
    for (;;) {
        http_reply_t *r;
        if (xQueueReceive(queue, &r, portMAX_DELAY) == pdTRUE) {
            void (*receive)(http_reply_t *) = r->receive;
            r->receive = NULL;
            if (receive) receive(r);
            else send_reply(r);
        }
    }
}

esp_err_t http_reply_init(void) {
    if (queue) return ESP_ERR_INVALID_STATE;
    queue = xQueueCreate(HTTP_REPLY_SLOTS, sizeof(http_reply_t *));
    if (!queue) return ESP_ERR_NO_MEM;
    for (unsigned i = 0; i < HTTP_REPLY_SLOTS; i++) {
        /* Socket IO only; flash/NVS operations retain internal stacks. */
        if (xTaskCreateWithCaps(sender, "http_reply", 4096, NULL, 5, &workers[i],
                                MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) != pdPASS) {
            while (i) vTaskDeleteWithCaps(workers[--i]);
            vQueueDelete(queue);
            queue = NULL;
            return ESP_ERR_NO_MEM;
        }
    }
    return ESP_OK;
}

http_reply_t *http_reply_begin(httpd_req_t *request) {
    http_reply_t *r = NULL;
    uint32_t now = now_ms();
    int fd = httpd_req_to_sockfd(request);
    portENTER_CRITICAL(&lock);
    for (unsigned i = 0; queue && i < HTTP_REPLY_SLOTS; i++) {
        if (status.slots[i].active) continue;
        r = &replies[i];
        *r = (http_reply_t){.started_ms = now};
        status.slots[i] = (http_reply_slot_status_t){
            .active = true, .stage = HTTP_REPLY_RECEIVING, .started_ms = now,
            .socket_fd = fd};
        status.active++;
        if (status.active > status.peak) status.peak = status.active;
        break;
    }
    if (!r) status.rejected++;
    portEXIT_CRITICAL(&lock);
    if (!r) return NULL;
    if (httpd_req_async_handler_begin(request, &r->request) != ESP_OK) {
        portENTER_CRITICAL(&lock);
        status.rejected++;
        portEXIT_CRITICAL(&lock);
        release(r, ESP_ERR_NO_MEM);
        return NULL;
    }
    portENTER_CRITICAL(&lock);
    status.accepted++;
    portEXIT_CRITICAL(&lock);
    return r;
}

httpd_req_t *http_reply_request(http_reply_t *r) { return r->request; }
uint32_t http_reply_started(http_reply_t *r) { return r->started_ms; }
void http_reply_abort(http_reply_t *r) { release(r, ESP_FAIL); }

esp_err_t http_reply_receive(http_reply_t *r, void (*receive)(http_reply_t *)) {
    r->receive = receive;
    if (receive && xQueueSend(queue, &r, 0) == pdTRUE) return ESP_OK;
    release(r, ESP_FAIL);
    return ESP_FAIL;
}

esp_err_t http_reply_send(http_reply_t *r, const char *data, size_t bytes,
                          bool owned, http_reply_done_t done) {
    r->data = data;
    r->bytes = bytes;
    r->owned = owned;
    r->done = done;
    portENTER_CRITICAL(&lock);
    status.slots[r - replies].stage = HTTP_REPLY_QUEUED;
    status.slots[r - replies].bytes = bytes;
    portEXIT_CRITICAL(&lock);
    if (xQueueSend(queue, &r, 0) == pdTRUE) return ESP_OK;
    release(r, ESP_FAIL);
    return ESP_FAIL;
}

void http_reply_snapshot(http_reply_status_t *out) {
    uint32_t now = now_ms();
    portENTER_CRITICAL(&lock);
    *out = status;
    portEXIT_CRITICAL(&lock);
    for (unsigned i = 0; i < HTTP_REPLY_SLOTS; i++)
        if (out->slots[i].active) out->slots[i].elapsed_ms = now - out->slots[i].started_ms;
}
