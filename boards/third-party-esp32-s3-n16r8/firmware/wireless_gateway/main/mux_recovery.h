#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

/* Recovery accepts only a fresh HELLO/EXIT reply, never target commands. */
static inline uint32_t mux_u32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static inline void mux_put(uint8_t *p, uint32_t n) {
    for (unsigned i=0;i<4;i++) p[i]=(uint8_t)(n>>(8*i));
}
static inline uint32_t mux_crc(const uint8_t *p, unsigned n) {
    uint32_t crc=~0u;
    while(n--) { crc^=*p++; for(unsigned b=0;b<8;b++) crc=(crc>>1)^(0xedb88320u & (0u-(crc&1))); }
    return ~crc;
}
static inline void mux_recovery_packet(uint8_t *p, uint8_t op, uint32_t epoch, uint32_t id) {
    memcpy(p,"MLX1",4);p[4]=1;p[5]=op;p[6]=p[7]=0;
    mux_put(p+8,epoch);mux_put(p+12,id);mux_put(p+16,mux_crc(p,16));
}
typedef struct {uint8_t data[29];unsigned used;} mux_recovery_reply_t;
static inline bool mux_recovery_feed(mux_recovery_reply_t *r, uint8_t byte,
                                    uint8_t op, uint32_t id, uint32_t *epoch) {
    unsigned n=op==1?29:21;
    if(r->used==n){memmove(r->data,r->data+1,n-1);r->used--;}
    r->data[r->used++]=byte;
    const uint8_t *p=r->data;
    if(r->used!=n || memcmp(p,"MLX1",4) || p[4]!=1 || p[5]!=(op|0x80) ||
       p[6]!=n-20 || p[7] || mux_u32(p+12)!=id || p[16] ||
       mux_u32(p+n-4)!=mux_crc(p,n-4))return false;
    if(op==1){if(!mux_u32(p+8)||(mux_u32(p+17)&3)!=3)return false;*epoch=mux_u32(p+8);}
    else if(mux_u32(p+8)!=*epoch)return false;
    return true;
}
