#include "mux_recovery.h"
#include <assert.h>
#include <stdio.h>
static bool feed(const uint8_t *p,unsigned n,uint8_t op,uint32_t id,uint32_t *epoch){
    mux_recovery_reply_t r={0};bool matched=false;
    for(unsigned i=0;i<1000;i++)assert(!mux_recovery_feed(&r,0x55,op,id,epoch));
    for(unsigned i=0;i<n;i++)matched|=mux_recovery_feed(&r,p[i],op,id,epoch);
    return matched;
}
int main(void){
    uint8_t request[20],reply[29]={0};uint32_t epoch=0;
    mux_recovery_packet(request,1,0,0x12345678);
    assert(mux_crc((const uint8_t*)"123456789",9)==0xcbf43926);
    assert(!memcmp(request,"MLX1\x01\x01\0\0\0\0\0\0\x78\x56\x34\x12",16));
    memcpy(reply,request,16);reply[5]=0x81;reply[6]=9;mux_put(reply+8,77);mux_put(reply+17,3);mux_put(reply+25,mux_crc(reply,25));
    assert(feed(reply,29,1,0x12345678,&epoch)&&epoch==77);
    assert(!feed(reply,28,1,0x12345678,&epoch));
    assert(!feed(reply,29,1,0x12345679,&epoch));
    for(unsigned i=0;i<29;i++){reply[i]^=1;assert(!feed(reply,29,1,0x12345678,&epoch));reply[i]^=1;}
    reply[5]=0x83;reply[6]=1;mux_put(reply+17,mux_crc(reply,17));
    assert(feed(reply,21,3,0x12345678,&epoch));epoch=78;
    assert(!feed(reply,21,3,0x12345678,&epoch));
    puts("MUX recovery: CRC golden vector, corruption, stale ID/epoch and fragmented replies PASS");
}
