#include "probe_transport.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
static unsigned calls;static bool uncertain;
static probe_result_t exchange(void *context,const uint8_t *in,size_t n,uint8_t *out,size_t capacity,size_t *written,unsigned timeout){(void)context;(void)timeout;calls++;if(uncertain)return PROBE_OUTCOME_UNKNOWN;if(capacity<n)return PROBE_INVALID;memcpy(out,in,n);*written=n;return PROBE_OK;}
static probe_result_t stream(void *context,probe_stream_op_t op,const uint8_t *in,size_t n,uint8_t *out,size_t cap,size_t *written){(void)context;(void)op;(void)in;(void)n;(void)out;(void)cap;calls++;*written=0;return uncertain?PROBE_OUTCOME_UNKNOWN:PROBE_OK;}
int main(void){
    probe_transport_t t={0};probe_descriptor_t d={.vid=0x0d28,.pid=0x0202,.speed=1,.interface_number=5,.in_endpoint=0x87,.out_endpoint=7,.in_mps=512,.out_mps=512};probe_backend_t b={.exchange=exchange};
    assert(!probe_transport_bind(&t,&d,&b));assert(!t.ready);d.in_mps=d.out_mps=64;assert(probe_transport_bind(&t,&d,&b));
    uint8_t payload[]={0,1,2,0xff},out[16];size_t written=0;const char *owner="0123456789abcdef0123456789abcdef";
    assert(probe_transport_exchange(&t,owner,1,t.generation,payload,sizeof(payload),out,sizeof(out),&written,100)==PROBE_OK);assert(written==sizeof(payload)&&!memcmp(out,payload,written));
    assert(probe_transport_exchange(&t,owner,1,t.generation,payload,sizeof(payload),out,sizeof(out),&written,100)==PROBE_DUPLICATE);assert(calls==1);
    unsigned previous_calls=calls;
    assert(probe_transport_exchange(&t,owner,2,t.generation-1,payload,sizeof(payload),out,sizeof(out),&written,100)==PROBE_STALE);assert(calls==previous_calls);
    uint32_t old_generation=t.generation;probe_transport_invalidate(&t);assert(probe_transport_bind(&t,&d,&b));
    assert(probe_transport_exchange(&t,owner,2,old_generation,payload,sizeof(payload),out,sizeof(out),&written,100)==PROBE_STALE);assert(calls==previous_calls);
    uncertain=true;assert(probe_transport_exchange(&t,owner,2,t.generation,payload,sizeof(payload),out,sizeof(out),&written,100)==PROBE_OUTCOME_UNKNOWN);assert(t.dirty);
    assert(probe_transport_exchange(&t,owner,3,t.generation,payload,sizeof(payload),out,sizeof(out),&written,100)==PROBE_OUTCOME_UNKNOWN);assert(calls==2);
    probe_transport_invalidate(&t);assert(probe_transport_exchange(&t,owner,4,t.generation,payload,sizeof(payload),out,sizeof(out),&written,100)==PROBE_NOT_READY);
    b.stream=stream;assert(probe_transport_bind(&t,&d,&b));uncertain=false;
    assert(probe_transport_stream(&t,owner,1,t.generation,PROBE_STREAM_OPEN,NULL,0,NULL,0,&written)==PROBE_OK);
    previous_calls=calls;
    assert(probe_transport_exchange(&t,owner,2,t.generation,payload,sizeof(payload),out,sizeof(out),&written,100)==PROBE_NOT_READY);
    assert(probe_transport_stream(&t,owner,2,t.generation-1,PROBE_STREAM_WRITE,payload,sizeof payload,NULL,0,&written)==PROBE_STALE);
    assert(probe_transport_stream(&t,"fedcba9876543210fedcba9876543210",2,t.generation,PROBE_STREAM_WRITE,payload,sizeof payload,NULL,0,&written)==PROBE_NOT_READY);
    assert(calls==previous_calls);
    assert(probe_transport_stream(&t,owner,2,t.generation,PROBE_STREAM_WRITE,payload,sizeof payload,NULL,0,&written)==PROBE_OK);
    assert(probe_transport_stream(&t,owner,2,t.generation,PROBE_STREAM_WRITE,payload,sizeof payload,NULL,0,&written)==PROBE_DUPLICATE);
    assert(probe_transport_stream(&t,owner,3,t.generation,PROBE_STREAM_READ,NULL,0,out,sizeof out,&written)==PROBE_OK);
    assert(probe_transport_stream(&t,owner,4,t.generation,PROBE_STREAM_CLOSE,NULL,0,NULL,0,&written)==PROBE_OK);
    assert(!t.stream_active);
    assert(probe_transport_stream(&t,owner,5,t.generation,PROBE_STREAM_OPEN,NULL,0,NULL,0,&written)==PROBE_OK);
    probe_transport_reconcile_owner(&t,NULL);assert(t.dirty);
    previous_calls=calls;
    assert(probe_transport_stream(&t,owner,6,t.generation,PROBE_STREAM_WRITE,payload,sizeof payload,NULL,0,&written)==PROBE_OUTCOME_UNKNOWN);
    assert(calls==previous_calls);
    probe_transport_t buffered={0};uint8_t large[PROBE_READ_MAX];uncertain=false;
    assert(probe_transport_bind(&buffered,&d,&b));
    assert(probe_transport_stream(&buffered,owner,1,buffered.generation,PROBE_STREAM_OPEN,NULL,0,NULL,0,&written)==PROBE_OK);
    previous_calls=calls;
    assert(probe_transport_stream(&buffered,owner,2,buffered.generation,PROBE_STREAM_READ,NULL,0,large,PROBE_READ_MAX+1,&written)==PROBE_INVALID);
    assert(probe_transport_stream(&buffered,owner,2,buffered.generation,PROBE_STREAM_WRITE,payload,PROBE_PAYLOAD_MAX+1,NULL,0,&written)==PROBE_INVALID);
    assert(calls==previous_calls);
    assert(probe_transport_stream(&buffered,owner,2,buffered.generation,PROBE_STREAM_READ,NULL,0,large,sizeof large,&written)==PROBE_OK);
    assert(probe_transport_stream(&buffered,owner,3,buffered.generation,PROBE_STREAM_CLOSE,NULL,0,NULL,0,&written)==PROBE_OK);
    puts("PASS: V4 descriptor guard, bounded4KiB read/1KiB write, generation/sequence and quarantine");return 0;
}
