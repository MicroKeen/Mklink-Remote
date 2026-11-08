#pragma once
#include <stdint.h>

enum { HTTP_DIAG_BEGIN, HTTP_DIAG_BODY, HTTP_DIAG_PROCESSED, HTTP_DIAG_SENT,
       HTTP_DIAG_RECV_ERROR, HTTP_DIAG_SEND_ERROR, HTTP_DIAG_ALLOC_ERROR, HTTP_DIAG_COUNT };
typedef struct {
    uint32_t counts[HTTP_DIAG_COUNT], stage, started_ms, elapsed_ms;
    int error;
} http_diagnostics_t;

/* Caller serializes updates and snapshots across HTTP and maintenance tasks. */
static inline void http_diagnostics_record(http_diagnostics_t *d, unsigned stage,
                                           uint32_t now, int error) {
    if (stage == HTTP_DIAG_BEGIN) d->started_ms = now;
    d->stage = stage;
    d->counts[stage]++;
    d->elapsed_ms = now - d->started_ms;
    d->error = error;
}

/* Concurrent response completions must retain their own request start time. */
static inline void http_diagnostics_record_request(http_diagnostics_t *d, unsigned stage,
                                                   uint32_t now, uint32_t started, int error) {
    http_diagnostics_record(d, stage, now, error);
    d->started_ms = started;
    d->elapsed_ms = now - started;
}
