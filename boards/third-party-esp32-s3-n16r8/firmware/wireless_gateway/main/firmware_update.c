/* Authenticated, explicit APP-only OTA. No bootloader, partitions or eFuse writes.
 * An ACK for a chunk means RAM acceptance; only READY proves flash readback.
 * One worker owns erase/write/verify. Unknown RPC outcomes are queried by job ID.
 */
#include "firmware_update.h"
#include "esp_app_desc.h"
#include "esp_app_format.h"
#include "esp_heap_caps.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "mbedtls/sha256.h"
#include "nvs.h"
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IMAGE_LIMIT (4U*1024U*1024U)
#define CHUNK_LIMIT 2048U
#define CONFIRM_TIMEOUT_MS 120000U
#define OTA_PROTOCOL_MARKER "MKLINK_NODE_OTA_V1"
/* Retained in the image; older APPs cannot satisfy the confirmation protocol. */
static const char protocol_marker[] __attribute__((used))=OTA_PROTOCOL_MARKER;
typedef enum {IDLE,RECEIVING,WRITING,READY,ACTIVATING,PENDING_VERIFY,CONFIRMING,CONFIRMED,FAILED,ABORTED,ROLLED_BACK,NOT_ACTIVATED} state_t;
static const char *const names[]={"idle","receiving","writing","ready","activating","pending_verify","confirming","confirmed","failed","aborted","rolled_back","not_activated"};
typedef struct {
    uint32_t magic,address,bytes,confirmed;
    char job[33],sha[65],version[32];
} saved_job_t;
static SemaphoreHandle_t guard;
static nvs_handle_t store;
static atomic_bool healthy;
/* RPC is serialized by guard. Keep decoding off the small BLE task stack. */
static uint8_t *decode_workspace;
static struct {
    state_t state;
    uint8_t *buffer;
    const esp_partition_t *slot;
    saved_job_t saved;
    char owner[33],error[128];
    size_t accepted,written;
    uint64_t activity_ms,reboot_ms,confirm_deadline_ms;
} update;
static uint64_t clock_ms(void){return esp_timer_get_time()/1000;}
static const char *text(const cJSON *p,const char *key){
    const cJSON *v=cJSON_GetObjectItemCaseSensitive(p,key);return cJSON_IsString(v)?v->valuestring:NULL;
}
static bool hex_text(const char *p,size_t n){
    if(!p||strlen(p)!=n)return false;
    for(size_t i=0;i<n;i++)if(!((p[i]>='0'&&p[i]<='9')||(p[i]>='a'&&p[i]<='f')))return false;
    return true;
}
static bool number(const cJSON *p,const char *key,size_t max,size_t *out){
    const cJSON *v=cJSON_GetObjectItemCaseSensitive(p,key);
    if(!cJSON_IsNumber(v)||v->valuedouble<0||v->valuedouble>max||v->valuedouble!=(size_t)v->valuedouble)return false;
    *out=(size_t)v->valuedouble;return true;
}
static bool busy_locked(void){return update.state>=RECEIVING&&update.state<=CONFIRMING;}
static cJSON *status_locked(void){
    cJSON *j=cJSON_CreateObject();
    const esp_partition_t *running=esp_ota_get_running_partition();
    cJSON_AddNumberToObject(j,"protocol",1);cJSON_AddStringToObject(j,"state",names[update.state]);
    cJSON_AddStringToObject(j,"job_id",update.saved.job);cJSON_AddStringToObject(j,"sha256",update.saved.sha);
    cJSON_AddStringToObject(j,"version",update.saved.version);cJSON_AddStringToObject(j,"error",update.error);
    cJSON_AddNumberToObject(j,"bytes",update.saved.bytes);cJSON_AddNumberToObject(j,"accepted_bytes",update.accepted);
    cJSON_AddNumberToObject(j,"written_bytes",update.written);cJSON_AddNumberToObject(j,"chunk_max",CHUNK_LIMIT);
    cJSON_AddNumberToObject(j,"image_max",IMAGE_LIMIT);cJSON_AddStringToObject(j,"running_slot",running?running->label:"");
    cJSON_AddStringToObject(j,"running_version",esp_app_get_description()->version);
    cJSON_AddStringToObject(j,"destination_slot",update.slot?update.slot->label:"");
    cJSON_AddBoolToObject(j,"health_ready",healthy);cJSON_AddBoolToObject(j,"busy",busy_locked());
    uint64_t now=clock_ms();
    cJSON_AddNumberToObject(j,"confirm_remaining_ms",update.state==PENDING_VERIFY&&update.confirm_deadline_ms>now?update.confirm_deadline_ms-now:0);
    return j;
}
bool firmware_update_busy(void){
    if(!guard)return false;
    xSemaphoreTake(guard,portMAX_DELAY);bool b=busy_locked();xSemaphoreGive(guard);return b;
}
cJSON *firmware_update_status(void){
    if(!guard)return NULL;
    xSemaphoreTake(guard,portMAX_DELAY);cJSON *j=status_locked();xSemaphoreGive(guard);return j;
}
void firmware_update_health_ready(void){healthy=true;}
static esp_err_t save_job(void){
    esp_err_t e=nvs_set_blob(store,"job",&update.saved,sizeof update.saved);
    return e==ESP_OK?nvs_commit(store):e;
}
static void fail_locked(const char *reason){
    snprintf(update.error,sizeof update.error,"%s",reason);update.state=FAILED;
    free(update.buffer);update.buffer=NULL;
}
static void hash_hex(const uint8_t digest[32],char out[65]){
    for(unsigned i=0;i<32;i++)snprintf(out+2*i,3,"%02x",digest[i]);
    out[64]=0;
}
static bool image_compatible(void){
    const size_t off=sizeof(esp_image_header_t)+sizeof(esp_image_segment_header_t);
    if(update.saved.bytes<off+sizeof(esp_app_desc_t))return false;
    esp_image_header_t h;esp_app_desc_t d;
    memcpy(&h,update.buffer,sizeof h);memcpy(&d,update.buffer+off,sizeof d);
    if(h.magic!=ESP_IMAGE_HEADER_MAGIC||h.chip_id!=ESP_CHIP_ID_ESP32S3||
       d.magic_word!=ESP_APP_DESC_MAGIC_WORD||!memchr(d.project_name,0,sizeof d.project_name)||
       strcmp(d.project_name,"n16r8_wireless_gateway")||!memchr(d.version,0,sizeof d.version))return false;
    bool found=false;
    for(size_t i=0;i+sizeof protocol_marker<=update.saved.bytes;i++)
        if(!memcmp(update.buffer+i,protocol_marker,sizeof protocol_marker)){found=true;break;}
    if(found)snprintf(update.saved.version,sizeof update.saved.version,"%s",d.version);
    return found;
}
static void write_staged_image(void){
    /* State WRITING prevents mutation/free by RPC or timeout. No guard held
     * across flash work so Wi-Fi/BLE status/lease renewal stays responsive. */
    esp_ota_handle_t handle=0;
    esp_err_t err=esp_ota_begin(update.slot,update.saved.bytes,&handle);
    if(err==ESP_OK){
        for(size_t offset=0;offset<update.saved.bytes&&err==ESP_OK;){
            size_t n=update.saved.bytes-offset;if(n>16384)n=16384;
            err=esp_ota_write(handle,update.buffer+offset,n);
            if(err==ESP_OK){offset+=n;xSemaphoreTake(guard,portMAX_DELAY);update.written=offset;xSemaphoreGive(guard);}
            vTaskDelay(1);
        }
        if(err==ESP_OK){err=esp_ota_end(handle);handle=0;}
    }
    if(handle)esp_ota_abort(handle);
    /* Exact file bytes, including ESP image trailer, must match source SHA. */
    uint8_t *scratch=heap_caps_malloc(8192,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    mbedtls_sha256_context hash;mbedtls_sha256_init(&hash);uint8_t digest[32];char hex[65]={0};
    if(err==ESP_OK&&!scratch)err=ESP_ERR_NO_MEM;
    if(err==ESP_OK&&mbedtls_sha256_starts(&hash,0))err=ESP_FAIL;
    for(size_t offset=0;offset<update.saved.bytes&&err==ESP_OK;){
        size_t n=update.saved.bytes-offset;if(n>8192)n=8192;
        err=esp_partition_read(update.slot,offset,scratch,n);
        if(err==ESP_OK&&mbedtls_sha256_update(&hash,scratch,n))err=ESP_FAIL;
        offset+=n;vTaskDelay(1);
    }
    if(err==ESP_OK&&mbedtls_sha256_finish(&hash,digest))err=ESP_FAIL;
    mbedtls_sha256_free(&hash);free(scratch);
    if(err==ESP_OK){hash_hex(digest,hex);if(strcmp(hex,update.saved.sha))err=ESP_ERR_INVALID_CRC;}
    xSemaphoreTake(guard,portMAX_DELAY);
    free(update.buffer);update.buffer=NULL;
    if(err==ESP_OK){update.state=READY;update.activity_ms=clock_ms();}
    else fail_locked(esp_err_to_name(err));
    xSemaphoreGive(guard);
}
static void activate_staged_image(void){
            esp_err_t err=save_job();
            if(err==ESP_OK)err=esp_ota_set_boot_partition(update.slot);
            xSemaphoreTake(guard,portMAX_DELAY);
            if(err==ESP_OK)update.reboot_ms=clock_ms()+2000;
            else fail_locked(esp_err_to_name(err));
            xSemaphoreGive(guard);
}
static void confirm_running_image(void){
            esp_err_t err=esp_ota_mark_app_valid_cancel_rollback();
            if(err==ESP_OK){xSemaphoreTake(guard,portMAX_DELAY);update.saved.confirmed=1;xSemaphoreGive(guard);err=save_job();
                xSemaphoreTake(guard,portMAX_DELAY);update.state=CONFIRMED;
                if(err!=ESP_OK)snprintf(update.error,sizeof update.error,"APP valid; metadata persistence failed");
            }else{xSemaphoreTake(guard,portMAX_DELAY);update.state=PENDING_VERIFY;
                snprintf(update.error,sizeof update.error,"SDK confirmation failed: %s",esp_err_to_name(err));}
            xSemaphoreGive(guard);
}
static void worker(void *arg){
    (void)arg;
    for(;;){
        bool write=false,activate=false,confirm=false,reboot=false,rollback=false;
        xSemaphoreTake(guard,portMAX_DELAY);uint64_t now=clock_ms();
        write=update.state==WRITING;
        activate=update.state==ACTIVATING&&update.reboot_ms==0;
        confirm=update.state==CONFIRMING;
        reboot=update.state==ACTIVATING&&update.reboot_ms!=0&&now>=update.reboot_ms;
        rollback=update.state==PENDING_VERIFY&&now>=update.confirm_deadline_ms;
        if(update.state==RECEIVING&&now-update.activity_ms>60000){free(update.buffer);update.buffer=NULL;update.state=ABORTED;}
        xSemaphoreGive(guard);
        if(write)write_staged_image();
        /* Flash/image validation runs on this task, outside both RPC stacks
         * and the status mutex. State gates prevent any mutation meanwhile. */
        if(activate)activate_staged_image();
        if(confirm)confirm_running_image();
        if(reboot)esp_restart();
        if(rollback){
            esp_err_t err=esp_ota_mark_app_invalid_rollback_and_reboot();
            /* SDK returns only when rollback is impossible. Keep the pending
             * APP unconfirmed; do not pretend a failed rollback succeeded. */
            xSemaphoreTake(guard,portMAX_DELAY);
            snprintf(update.error,sizeof update.error,"Rollback failed: %s",esp_err_to_name(err));
            update.confirm_deadline_ms=clock_ms()+30000;
            xSemaphoreGive(guard);
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
esp_err_t firmware_update_init(void){
    guard=xSemaphoreCreateMutex();if(!guard)return ESP_ERR_NO_MEM;
    decode_workspace=heap_caps_malloc(CHUNK_LIMIT,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!decode_workspace)return ESP_ERR_NO_MEM;
    esp_err_t err=nvs_open("mkota",NVS_READWRITE,&store);if(err!=ESP_OK)return err;
    const esp_partition_t *running=esp_ota_get_running_partition();esp_ota_img_states_t state=ESP_OTA_IMG_UNDEFINED;
    saved_job_t saved;size_t n=sizeof saved;
    if(nvs_get_blob(store,"job",&saved,&n)==ESP_OK&&n==sizeof saved&&saved.magic==0x4d4f5431&&
       memchr(saved.job,0,sizeof saved.job)&&memchr(saved.sha,0,sizeof saved.sha)&&
       hex_text(saved.job,32)&&hex_text(saved.sha,64)&&memchr(saved.version,0,sizeof saved.version)&&
       saved.bytes>=1024&&saved.bytes<=IMAGE_LIMIT){
        update.saved=saved;
        if(running&&running->address==saved.address){
            update.slot=running;update.accepted=update.written=saved.bytes;
            if(esp_ota_get_state_partition(running,&state)==ESP_OK&&state==ESP_OTA_IMG_PENDING_VERIFY){
                update.state=PENDING_VERIFY;update.confirm_deadline_ms=clock_ms()+CONFIRM_TIMEOUT_MS;
            }else if(state==ESP_OTA_IMG_VALID||saved.confirmed)update.state=CONFIRMED;
            else update.state=NOT_ACTIVATED;
        }else{
            esp_partition_iterator_t it=esp_partition_find(ESP_PARTITION_TYPE_APP,ESP_PARTITION_SUBTYPE_ANY,NULL);
            update.slot=NULL;
            while(it){const esp_partition_t *candidate=esp_partition_get(it);
                if(candidate->address==saved.address){update.slot=candidate;break;}
                it=esp_partition_next(it);}
            esp_partition_iterator_release(it);
            update.state=update.slot&&esp_ota_get_state_partition(update.slot,&state)==ESP_OK&&
                (state==ESP_OTA_IMG_INVALID||state==ESP_OTA_IMG_ABORTED)?ROLLED_BACK:NOT_ACTIVATED;
        }
    }else if(running&&esp_ota_get_state_partition(running,&state)==ESP_OK&&state==ESP_OTA_IMG_PENDING_VERIFY){
        update.state=PENDING_VERIFY;update.confirm_deadline_ms=clock_ms()+CONFIRM_TIMEOUT_MS;
        snprintf(update.error,sizeof update.error,"Missing OTA job metadata; confirmation refused");
    }
    return xTaskCreate(worker,"node_ota",12288,NULL,2,NULL)==pdPASS?ESP_OK:ESP_ERR_NO_MEM;
}
cJSON *firmware_update_rpc(const char *method,const cJSON *p,const char *owner,int *code,const char **message){
    cJSON *result=NULL;*code=409;*message="OTA state or job rejected; query status before retrying";
    if(!guard){*code=503;*message="OTA service unavailable";return NULL;}
    xSemaphoreTake(guard,portMAX_DELAY);
    if(!strcmp(method,"firmware.status")){result=status_locked();goto done;}
    const char *job=text(p,"job_id");
    if(!owner||strlen(owner)!=32){*code=423;*message="Acquire control before firmware update";goto done;}
    if(!strcmp(method,"firmware.begin")){
        size_t total;const char *sha=text(p,"sha256");
        if(!hex_text(job,32)||!hex_text(sha,64)||!number(p,"bytes",IMAGE_LIMIT,&total)||total<1024){*code=400;*message="Bounded APP image size, SHA256 and unique job ID required";goto done;}
        if(busy_locked())goto done;
        const esp_partition_t *slot=esp_ota_get_next_update_partition(NULL);
        const esp_partition_t *running=esp_ota_get_running_partition();
        if(!slot||!running||slot->address==running->address||slot->size<total||slot->type!=ESP_PARTITION_TYPE_APP||
           slot->subtype<ESP_PARTITION_SUBTYPE_APP_OTA_MIN||slot->subtype>=ESP_PARTITION_SUBTYPE_APP_OTA_MAX){*message="Inactive OTA partition unavailable";goto done;}
        uint8_t *buffer=heap_caps_malloc(total,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
        if(!buffer){*code=503;*message="Insufficient PSRAM for complete image staging";goto done;}
        free(update.buffer);memset(&update,0,sizeof update);update.buffer=buffer;update.slot=slot;
        update.saved.magic=0x4d4f5431;update.saved.address=slot->address;update.saved.bytes=total;
        strcpy(update.saved.job,job);strcpy(update.saved.sha,sha);strcpy(update.owner,owner);
        update.state=RECEIVING;update.activity_ms=clock_ms();
    }else{
        if(!job||strcmp(job,update.saved.job))goto done;
        if(!strcmp(method,"firmware.claim")){
            const char *sha=text(p,"sha256");
            if(!sha||strcmp(sha,update.saved.sha)||!busy_locked()||update.state==ACTIVATING||update.state==CONFIRMING)goto done;
            strcpy(update.owner,owner);update.activity_ms=clock_ms();
        }else{
            /* A reboot clears the old lease; only authenticated new owner
             * claiming this exact job+hash can confirm the pending APP. */
            if(strcmp(owner,update.owner)){*code=423;*message="Claim the existing OTA job with its SHA256 after reconnecting";goto done;}
            if(!strcmp(method,"firmware.write")){
                size_t offset,n=0;const char *encoded=text(p,"data_base64");
                uint8_t *bytes=decode_workspace;
                if(update.state!=RECEIVING||!number(p,"offset",update.saved.bytes,&offset)||offset!=update.accepted||
                   !encoded||mbedtls_base64_decode(bytes,CHUNK_LIMIT,&n,(const uint8_t*)encoded,strlen(encoded))||
                   !n||n>update.saved.bytes-offset){*code=400;*message="Sequential chunk required; query accepted_bytes after uncertainty";goto done;}
                memcpy(update.buffer+offset,bytes,n);update.accepted+=n;update.activity_ms=clock_ms();
            }else if(!strcmp(method,"firmware.finish")){
                if(update.state!=RECEIVING||update.accepted!=update.saved.bytes)goto done;
                uint8_t digest[32];char hex[65];
                if(mbedtls_sha256(update.buffer,update.saved.bytes,digest,0)){fail_locked("PSRAM image hashing failed");goto done;}
                hash_hex(digest,hex);
                if(strcmp(hex,update.saved.sha)||!image_compatible()){fail_locked("Image hash, chip, project or OTA protocol mismatch");*code=400;*message="Staged image rejected before flash erase";goto done;}
                update.state=WRITING;
            }else if(!strcmp(method,"firmware.activate")){
                if(update.state!=READY)goto done;
                update.state=ACTIVATING;update.reboot_ms=0;
            }else if(!strcmp(method,"firmware.confirm")){
                const esp_partition_t *running=esp_ota_get_running_partition();
                if(update.state!=PENDING_VERIFY||!healthy||!running||running->address!=update.saved.address)goto done;
                update.state=CONFIRMING;
            }else if(!strcmp(method,"firmware.abort")){
                if(update.state!=RECEIVING&&update.state!=READY)goto done;
                free(update.buffer);update.buffer=NULL;update.state=ABORTED;
            }else{*code=404;*message="Unsupported firmware update operation";goto done;}
        }
    }
    result=status_locked();
done:
    xSemaphoreGive(guard);return result;
}
