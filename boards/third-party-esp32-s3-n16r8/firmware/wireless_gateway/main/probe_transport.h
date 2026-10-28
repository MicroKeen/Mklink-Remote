#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
/* Stable boundary for the future V4 USB backend. The Wi-Fi/BLE/RPC layers
 * exchange opaque bytes; MKLink command parsing stays with the upper runtime.
 * Registration/close are serialized by the node executor, never from USB ISR. */
#define PROBE_PAYLOAD_MAX 1024
#define PROBE_READ_MAX 32768
typedef enum {PROBE_OK,PROBE_NOT_READY,PROBE_INVALID,PROBE_DUPLICATE,PROBE_OUTCOME_UNKNOWN,PROBE_STALE} probe_result_t;
typedef enum {PROBE_STREAM_OPEN,PROBE_STREAM_READ,PROBE_STREAM_WRITE,PROBE_STREAM_CLOSE} probe_stream_op_t;
typedef struct {uint16_t vid,pid,in_mps,out_mps;uint8_t interface_number,in_endpoint,out_endpoint,speed;} probe_descriptor_t;
typedef struct {
    void *context;
    probe_result_t (*exchange)(void*,const uint8_t*,size_t,uint8_t*,size_t,size_t*,unsigned);
    probe_result_t (*stream)(void*,probe_stream_op_t,const uint8_t*,size_t,uint8_t*,size_t,size_t*);
} probe_backend_t;
typedef struct {probe_backend_t backend;probe_descriptor_t descriptor;uint32_t generation,last_sequence;bool ready,dirty,stream_active;char controller[33];} probe_transport_t;
bool probe_descriptor_compatible(const probe_descriptor_t *descriptor);
bool probe_transport_bind(probe_transport_t *transport,const probe_descriptor_t *descriptor,const probe_backend_t *backend);
void probe_transport_invalidate(probe_transport_t *transport);
probe_result_t probe_transport_exchange(probe_transport_t *transport,const char *controller,uint32_t sequence,uint32_t expected_generation,const uint8_t *request,size_t request_bytes,uint8_t *reply,size_t reply_capacity,size_t *reply_bytes,unsigned timeout_ms);
probe_result_t probe_transport_stream(probe_transport_t*,const char*,uint32_t,uint32_t,probe_stream_op_t,const uint8_t*,size_t,uint8_t*,size_t,size_t*);
/* Losing the owner of a binary stream invalidates it. No stop bytes or target
 * commands are injected into an unknown protocol state. Explicit USB recovery
 * is required; a new lease must never inherit a previous byte stream. */
void probe_transport_reconcile_owner(probe_transport_t*,const char *current_owner);
