#pragma once
#include "esp_http_server.h"
#include <stdbool.h>
#include <stdint.h>

#define HTTP_REPLY_SLOTS 3
enum {HTTP_REPLY_IDLE, HTTP_REPLY_RECEIVING, HTTP_REPLY_QUEUED,
      HTTP_REPLY_SENDING, HTTP_REPLY_DONE, HTTP_REPLY_FAILED};
typedef struct {
    uint32_t stage, started_ms, elapsed_ms, bytes;
    int socket_fd, error;
    bool active;
} http_reply_slot_status_t;
typedef struct {
    uint32_t accepted, rejected, completed, send_errors, completion_errors;
    uint32_t active, peak, stack_min_bytes;
    http_reply_slot_status_t slots[HTTP_REPLY_SLOTS];
} http_reply_status_t;
typedef struct http_reply http_reply_t;
typedef void (*http_reply_done_t)(uint32_t started_ms, esp_err_t error);

esp_err_t http_reply_init(void);
/* Reserve before executing commands; NULL leaves the original request owned by HTTPD. */
http_reply_t *http_reply_begin(httpd_req_t *request);
httpd_req_t *http_reply_request(http_reply_t *reply);
uint32_t http_reply_started(http_reply_t *reply);
/* Socket work only: callback owns reply and must send, abort or transfer it. */
esp_err_t http_reply_receive(http_reply_t *reply, void (*receive)(http_reply_t *));
/* Always consumes reply and, if owned, data, including on queue failure. */
esp_err_t http_reply_send(http_reply_t *reply, const char *data, size_t bytes,
                          bool owned, http_reply_done_t done);
void http_reply_abort(http_reply_t *reply);
void http_reply_snapshot(http_reply_status_t *status);
