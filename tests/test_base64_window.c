#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "mbedtls/base64.h"
static uint8_t input[32768],decoded[32768];
static unsigned char encoded[((32768+2)/3)*4+1];
int main(void){
    for(size_t i=0;i<sizeof input;i++)input[i]=(uint8_t)i;
    for(size_t size=32766;size<=32768;size++){
        size_t n=0,back=0;
        assert(mbedtls_base64_encode(encoded,sizeof encoded,&n,input,size)==0);
        assert(encoded[n]==0);
        assert(mbedtls_base64_decode(decoded,sizeof decoded,&back,encoded,n)==0);
        assert(back==size&&!memcmp(input,decoded,size));
    }
    size_t n=0;
    assert(mbedtls_base64_encode(encoded,sizeof encoded-1,&n,input,sizeof input)==MBEDTLS_ERR_BASE64_BUFFER_TOO_SMALL);
    assert(n==sizeof encoded);
    puts("PASS actual pinned mbedTLS32766/32767/32768-byte roundtrip and exact terminator capacity regression");
}
