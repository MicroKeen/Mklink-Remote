#include <assert.h>
#include "firmware_update.c"
unsigned mock_begin_calls,mock_write_calls,mock_end_calls,mock_boot_calls,mock_confirm_calls;
uint8_t mock_image[1024],mock_flash[4096];size_t mock_decode_bytes=1024;
esp_partition_t mock_factory={.address=0x10000,.size=0x400000,.label="factory"};
esp_partition_t mock_ota={.address=0x420000,.size=0x400000,.type=0,.subtype=16,.label="ota_0"};
esp_partition_t mock_current;
esp_ota_img_states_t mock_boot_state;
bool mock_corrupt_readback;
static const char *owner="11111111111111111111111111111111",*other="22222222222222222222222222222222",*job="33333333333333333333333333333333";
static char digest[65];
static void image(bool compatible){
    memset(mock_image,0,sizeof mock_image);esp_image_header_t h={.magic=0xe9,.chip_id=9};
    esp_app_desc_t d={.magic_word=ESP_APP_DESC_MAGIC_WORD,.project_name="n16r8_wireless_gateway",.version="0.6.2"};
    memcpy(mock_image,&h,sizeof h);memcpy(mock_image+sizeof h+sizeof(esp_image_segment_header_t),&d,sizeof d);
    if(compatible)memcpy(mock_image+500,protocol_marker,sizeof protocol_marker);
    uint8_t sum[32];mbedtls_sha256(mock_image,sizeof mock_image,sum,0);hash_hex(sum,digest);
}
static cJSON *params(void){cJSON*p=cJSON_CreateObject();cJSON_AddStringToObject(p,"job_id",job);return p;}
static bool call(const char*m,cJSON*p,const char*who){int code;const char*error;cJSON*r=firmware_update_rpc(m,p,who,&code,&error);bool ok=r!=NULL;cJSON_Delete(r);cJSON_Delete(p);return ok;}
static bool begin(const char*sha){cJSON*p=params();cJSON_AddNumberToObject(p,"bytes",1024);cJSON_AddStringToObject(p,"sha256",sha);return call("firmware.begin",p,owner);}
static bool chunk(size_t offset,const char*who){cJSON*p=params();cJSON_AddNumberToObject(p,"offset",offset);cJSON_AddStringToObject(p,"data_base64","MOCK");return call("firmware.write",p,who);}
static void reset(void){free(update.buffer);memset(&update,0,sizeof update);healthy=false;mock_current=mock_factory;mock_begin_calls=mock_write_calls=mock_end_calls=mock_boot_calls=mock_confirm_calls=0;mock_corrupt_readback=false;guard=(void*)1;}
int main(void){
    decode_workspace=malloc(CHUNK_LIMIT);assert(decode_workspace);
    reset();image(true);assert(!begin("bad"));assert(!mock_begin_calls);
    assert(begin(digest));assert(firmware_update_busy());assert(!begin(digest));
    assert(!chunk(0,other));assert(!chunk(10,owner));assert(update.accepted==0);
    assert(!call("firmware.finish",params(),owner));assert(!mock_begin_calls);
    assert(chunk(0,owner));assert(!chunk(0,owner));assert(update.accepted==1024);
    assert(call("firmware.abort",params(),owner));assert(!firmware_update_busy()&&!mock_begin_calls);
    reset();image(true);char wrong[65];memset(wrong,'0',64);wrong[64]=0;
    assert(begin(wrong));assert(chunk(0,owner));assert(!call("firmware.finish",params(),owner));assert(update.state==FAILED&&!mock_begin_calls);
    reset();image(false);assert(begin(digest));assert(chunk(0,owner));assert(!call("firmware.finish",params(),owner));assert(!mock_begin_calls);
    reset();image(true);assert(begin(digest));assert(chunk(0,owner));assert(call("firmware.finish",params(),owner));
    assert(update.state==WRITING&&!mock_begin_calls);assert(!call("firmware.abort",params(),owner));
    assert(!call("firmware.activate",params(),owner));write_staged_image();
    assert(update.state==READY&&mock_begin_calls==1&&mock_write_calls==1&&mock_end_calls==1&&!mock_boot_calls);
    assert(call("firmware.activate",params(),owner));assert(mock_boot_calls==0&&update.state==ACTIVATING&&update.reboot_ms==0);
    activate_staged_image();assert(mock_boot_calls==1&&update.reboot_ms>0);
    assert(!call("firmware.activate",params(),owner));assert(mock_boot_calls==1);
    update.state=PENDING_VERIFY;mock_current=mock_ota;update.owner[0]=0;
    assert(!call("firmware.confirm",params(),owner));
    cJSON*p=params();cJSON_AddStringToObject(p,"sha256",wrong);assert(!call("firmware.claim",p,owner));
    p=params();cJSON_AddStringToObject(p,"sha256",digest);assert(call("firmware.claim",p,owner));
    assert(!call("firmware.confirm",params(),owner));assert(!mock_confirm_calls);
    firmware_update_health_ready();assert(call("firmware.confirm",params(),owner));assert(mock_confirm_calls==0&&update.state==CONFIRMING);
    assert(!call("firmware.confirm",params(),owner));
    confirm_running_image();assert(mock_confirm_calls==1&&update.state==CONFIRMED);
    reset();image(true);assert(begin(digest));assert(chunk(0,owner));assert(call("firmware.finish",params(),owner));
    mock_corrupt_readback=true;write_staged_image();assert(update.state==FAILED&&!mock_boot_calls);
    puts("PASS OTA ownership/order/hash/protocol/async-write/readback/activation/confirmation guards; crypto/platform mocked");
}
