#include <assert.h>
#include "http_diagnostics.h"

int main(void) {
    http_diagnostics_t d = {0};
    http_diagnostics_record(&d, HTTP_DIAG_BEGIN, UINT32_MAX - 4, 0);
    http_diagnostics_record(&d, HTTP_DIAG_BODY, UINT32_MAX - 1, 0);
    http_diagnostics_record(&d, HTTP_DIAG_PROCESSED, 2, 0);
    http_diagnostics_record(&d, HTTP_DIAG_SEND_ERROR, 5, -1);
    assert(d.elapsed_ms == 10 && d.error == -1);
    assert(d.counts[HTTP_DIAG_SENT] == 0 && d.counts[HTTP_DIAG_SEND_ERROR] == 1);
    http_diagnostics_record(&d, HTTP_DIAG_BEGIN, 20, 0);
    assert(d.elapsed_ms == 0 && d.error == 0 && d.counts[HTTP_DIAG_BEGIN] == 2);
    http_diagnostics_record(&d, HTTP_DIAG_RECV_ERROR, 30, -3);
    assert(d.stage == HTTP_DIAG_RECV_ERROR && d.elapsed_ms == 10);
    assert(d.counts[HTTP_DIAG_BODY] == 1 && d.counts[HTTP_DIAG_RECV_ERROR] == 1);
    http_diagnostics_record(&d, HTTP_DIAG_BEGIN, 40, 0);
    http_diagnostics_record(&d, HTTP_DIAG_BODY, 41, 0);
    http_diagnostics_record(&d, HTTP_DIAG_PROCESSED, 42, 0);
    http_diagnostics_record(&d, HTTP_DIAG_SENT, 43, 0);
    assert(d.counts[HTTP_DIAG_SENT] == 1 && d.counts[HTTP_DIAG_PROCESSED] == 2);
    assert(d.stage == HTTP_DIAG_SENT && d.error == 0);
    http_diagnostics_record_request(&d,HTTP_DIAG_BEGIN,100,100,0);
    http_diagnostics_record_request(&d,HTTP_DIAG_BEGIN,200,200,0);
    http_diagnostics_record_request(&d,HTTP_DIAG_SENT,230,200,0);
    http_diagnostics_record_request(&d,HTTP_DIAG_SENT,300,100,0);
    assert(d.started_ms==100 && d.elapsed_ms==200); /* Slow first request finishes last. */
    return 0;
}
