#pragma once
#include "esp_err.h"
#include "probe_transport.h"
#include "usb/usb_host.h"
typedef struct {
    char state[24], version[160], error[128];
    unsigned address, in_mps, out_mps;
    unsigned rx_pending,rx_peak,rx_capacity,rx_overflows;
    uint64_t measure_rx_bytes,measure_tx_bytes,measure_start_us,measure_tx_start_us,measure_first_rx_us,measure_last_rx_us;
} v4_backend_status_t;
/* CDC handle ownership is in the USB monitor task. Callbacks only signal events. */
esp_err_t v4_backend_start(void);
void v4_backend_attach(unsigned address, usb_device_handle_t device);
void v4_backend_detach(unsigned address);
void v4_backend_snapshot(v4_backend_status_t *out);
void v4_backend_metrics_reset(void);
