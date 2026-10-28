#include "probe_transport.h"
#include <string.h>
bool probe_descriptor_compatible(const probe_descriptor_t *d) {
    if (!d || d->vid != 0x0d28 || d->pid != 0x0202 || !(d->in_endpoint & 0x80) || (d->out_endpoint & 0x80) ||
        !(d->in_endpoint & 15) || !(d->out_endpoint & 15))
        return false;
    if (d->speed == 1)
        return (d->in_mps == 8 || d->in_mps == 16 || d->in_mps == 32 || d->in_mps == 64) &&
               (d->out_mps == 8 || d->out_mps == 16 || d->out_mps == 32 || d->out_mps == 64);
    return false; /* S3 OTG hardware path is Full-Speed; do not admit HS-only descriptors. */
}
bool probe_transport_bind(probe_transport_t *t, const probe_descriptor_t *d, const probe_backend_t *backend) {
    if (!t || !backend || !backend->exchange || !probe_descriptor_compatible(d))
        return false;
    t->backend = *backend;
    t->descriptor = *d;
    t->ready = true;
    t->dirty = false;
    t->stream_active = false;
    t->generation++;
    t->last_sequence = 0;
    t->controller[0] = 0;
    return true;
}
void probe_transport_invalidate(probe_transport_t *t) {
    if (t) {
        t->ready = false;
        t->generation++;
    }
}
probe_result_t probe_transport_exchange(probe_transport_t *t, const char *controller, uint32_t sequence, uint32_t expected_generation,
                                        const uint8_t *request, size_t request_bytes, uint8_t *reply,
                                        size_t capacity, size_t *reply_bytes, unsigned timeout) {
    if (reply_bytes)
        *reply_bytes = 0;
    if (!t || !controller || strlen(controller) != 32 || !sequence || !request || !request_bytes ||
        request_bytes > PROBE_PAYLOAD_MAX || !reply || capacity > PROBE_PAYLOAD_MAX || !reply_bytes ||
        !timeout || timeout > 5000)
        return PROBE_INVALID;
    if (!t->ready || !t->backend.exchange)
        return PROBE_NOT_READY;
    if (expected_generation != t->generation)
        return PROBE_STALE;
    if (t->dirty)
        return PROBE_OUTCOME_UNKNOWN;
    if (t->stream_active)
        return PROBE_NOT_READY;
    if (strcmp(t->controller, controller)) {
        strcpy(t->controller, controller);
        t->last_sequence = 0;
    }
    if (sequence <= t->last_sequence)
        return PROBE_DUPLICATE;
    t->last_sequence = sequence;
    uint32_t generation = t->generation;
    probe_result_t result = t->backend.exchange(t->backend.context, request, request_bytes, reply, capacity,
                                                reply_bytes, timeout);
    if (generation != t->generation || *reply_bytes > capacity || result == PROBE_OUTCOME_UNKNOWN) {
        t->dirty = true;
        *reply_bytes = 0;
        return PROBE_OUTCOME_UNKNOWN;
    }
    return result;
}
void probe_transport_reconcile_owner(probe_transport_t *t,const char *owner) {
    if(t&&t->stream_active&&(!owner||strcmp(owner,t->controller)))t->dirty=true;
}
probe_result_t probe_transport_stream(probe_transport_t *t,const char *owner,uint32_t seq,uint32_t generation,
                                     probe_stream_op_t op,const uint8_t *in,size_t n,uint8_t *out,size_t cap,size_t *written) {
    if(written)*written=0;
    if(!t||!owner||strlen(owner)!=32||!seq||!written||op>PROBE_STREAM_CLOSE||
       n>PROBE_PAYLOAD_MAX||cap>PROBE_READ_MAX||
       (op==PROBE_STREAM_WRITE?(!in||!n):n!=0)||
       (op==PROBE_STREAM_READ&&(!out||!cap)))return PROBE_INVALID;
    if(!t->ready||!t->backend.stream)return PROBE_NOT_READY;
    if(generation!=t->generation)return PROBE_STALE;
    if(t->dirty)return PROBE_OUTCOME_UNKNOWN;
    if(t->stream_active&&strcmp(owner,t->controller))return PROBE_NOT_READY;
    if(op==PROBE_STREAM_OPEN?t->stream_active:!t->stream_active)return PROBE_NOT_READY;
    if(strcmp(owner,t->controller)){strcpy(t->controller,owner);t->last_sequence=0;}
    if(seq<=t->last_sequence)return PROBE_DUPLICATE;
    t->last_sequence=seq;
    probe_result_t rc=t->backend.stream(t->backend.context,op,in,n,out,cap,written);
    if(rc==PROBE_OUTCOME_UNKNOWN||generation!=t->generation||*written>cap){
        t->dirty=true;*written=0;return PROBE_OUTCOME_UNKNOWN;
    }
    if(rc==PROBE_OK){
        if(op==PROBE_STREAM_OPEN)t->stream_active=true;
        if(op==PROBE_STREAM_CLOSE)t->stream_active=false;
    }
    return rc;
}
