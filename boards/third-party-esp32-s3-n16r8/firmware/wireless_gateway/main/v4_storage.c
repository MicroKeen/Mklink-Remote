/* USB MSC file delivery for native MKLink FLM/load.bin operations.
 * No formatting, firmware updates, arbitrary paths, or target commands here.
 * Lock order: config RPC -> storage; USB callbacks never take either lock.
 */
#include "v4_storage.h"
#include "usb/msc_host.h"
#include "usb/msc_host_vfs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_heap_caps.h"
#include "mbedtls/base64.h"
#include "mbedtls/sha256.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdatomic.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#define FILE_LIMIT 1048576U
static SemaphoreHandle_t guard;
static msc_host_device_handle_t disk;
static msc_host_vfs_handle_t vfs;
static atomic_bool gone;
static char serial_number[40];
static struct {
    FILE *file;
    uint8_t *buffer;
    char id[17],owner[33],sha[65],temporary[64],final[64],remote[40];
    size_t total,offset;
} upload;
static bool integer(const cJSON *p,const char *key,size_t max,size_t *out){
    const cJSON *v=cJSON_GetObjectItemCaseSensitive(p,key);
    if(!cJSON_IsNumber(v)||v->valuedouble<0||v->valuedouble>max||v->valuedouble!=(size_t)v->valuedouble)return false;
    *out=(size_t)v->valuedouble;return true;
}
static const char *text(const cJSON *p,const char *key){
    const cJSON *v=cJSON_GetObjectItemCaseSensitive(p,key);return cJSON_IsString(v)?v->valuestring:NULL;
}
static bool digest_file(const char *path,char hex[65],size_t *bytes){
    FILE *file=fopen(path,"rb");if(!file)return false;
    mbedtls_sha256_context hash;mbedtls_sha256_init(&hash);
    unsigned char buffer[512],digest[32];size_t n;*bytes=0;
    bool ok=mbedtls_sha256_starts(&hash,0)==0;
    while(ok&&(n=fread(buffer,1,sizeof buffer,file))){
        *bytes+=n;if(*bytes>FILE_LIMIT||gone)ok=false;
        else ok=mbedtls_sha256_update(&hash,buffer,n)==0;
    }
    if(ferror(file))ok=false;
    if(ok)ok=mbedtls_sha256_finish(&hash,digest)==0;
    mbedtls_sha256_free(&hash);if(fclose(file))ok=false;
    if(ok){for(unsigned i=0;i<32;i++)snprintf(hex+2*i,3,"%02x",digest[i]);hex[64]=0;}
    return ok;
}
static void abort_locked(void){
    if(upload.file){fclose(upload.file);upload.file=NULL;}
    free(upload.buffer);upload.buffer=NULL;
    /* Only this session's generated temporary file can be removed. */
    if(upload.temporary[0]&&vfs&&!gone)unlink(upload.temporary);
    memset(&upload,0,sizeof upload);
}
static void event(const msc_host_event_t *e,void *arg){
    (void)arg;if(e->event==MSC_DEVICE_DISCONNECTED)gone=true;
}
esp_err_t v4_storage_start(void){
    guard=xSemaphoreCreateMutex();if(!guard)return ESP_ERR_NO_MEM;
    const msc_host_driver_config_t cfg={.create_backround_task=true,.task_priority=5,.stack_size=4096,.core_id=0,.callback=event};
    return msc_host_install(&cfg);
}
void v4_storage_attach(unsigned address){
    xSemaphoreTake(guard,portMAX_DELAY);
    if(disk){xSemaphoreGive(guard);return;}
    gone=false;esp_err_t err=msc_host_install_device(address,&disk);
    if(err==ESP_OK){
        msc_host_device_info_t info;
        err=msc_host_get_device_info(disk,&info);
        if(err==ESP_OK&&(info.idVendor!=0x0d28||info.idProduct!=0x0202))err=ESP_ERR_INVALID_ARG;
        if(err==ESP_OK){
            for(unsigned i=0;i<sizeof serial_number-1&&i<MSC_STR_DESC_SIZE&&info.iSerialNumber[i];i++)
                serial_number[i]=(char)(info.iSerialNumber[i]<128?info.iSerialNumber[i]:'?');
            const esp_vfs_fat_mount_config_t cfg={.format_if_mount_failed=false,.max_files=3,.allocation_unit_size=4096};
            err=msc_host_vfs_register(disk,"/v4",&cfg,&vfs);
        }
        if(err!=ESP_OK){msc_host_uninstall_device(disk);disk=NULL;}
    }
    ESP_LOGI("v4_storage","MSC mount=%s serial=%s format=NEVER",esp_err_to_name(err),serial_number);
    xSemaphoreGive(guard);
}
void v4_storage_detach(void){
    if(!guard)return;
    xSemaphoreTake(guard,portMAX_DELAY);gone=true;abort_locked();
    if(vfs){msc_host_vfs_unregister(vfs);vfs=NULL;}
    if(disk){msc_host_uninstall_device(disk);disk=NULL;}
    memset(serial_number,0,sizeof serial_number);xSemaphoreGive(guard);
}
bool v4_storage_ready(void){
    if(!guard||xSemaphoreTake(guard,0)!=pdTRUE)return false;
    const bool ready=vfs&&!gone;
    xSemaphoreGive(guard);return ready;
}
bool v4_storage_upload_active(void){
    if(!guard)return false;
    xSemaphoreTake(guard,portMAX_DELAY);bool active=upload.id[0]!=0;xSemaphoreGive(guard);return active;
}
void v4_storage_reconcile_owner(const char *owner){
    if(!guard)return;
    xSemaphoreTake(guard,portMAX_DELAY);
    if(upload.id[0]&&(!owner||strcmp(owner,upload.owner)))abort_locked();
    xSemaphoreGive(guard);
}
cJSON *v4_storage_rpc(const char *method,const cJSON *p,const char *owner,int *code,const char **message){
    cJSON *result=NULL;*code=409;*message="Storage or upload state rejected; do not replay";
    xSemaphoreTake(guard,portMAX_DELAY);
    if(!vfs||gone)goto done;
    if(!strcmp(method,"probe.files.status")){
        result=cJSON_CreateObject();cJSON_AddBoolToObject(result,"mounted",true);
        cJSON_AddStringToObject(result,"serial",serial_number);cJSON_AddNumberToObject(result,"max_file_bytes",FILE_LIMIT);
        cJSON_AddBoolToObject(result,"upload_active",upload.id[0]!=0);
        cJSON_AddStringToObject(result,"staging","psram_until_verified_commit");
        if(upload.id[0]&&!strcmp(owner,upload.owner)){cJSON_AddStringToObject(result,"upload_id",upload.id);cJSON_AddNumberToObject(result,"offset",upload.offset);}
    }else if(!strcmp(method,"probe.files.begin")){
        const char *sha=text(p,"sha256"),*kind=text(p,"kind");size_t total;
        if(upload.id[0])goto done;
        if(!sha||strlen(sha)!=64||strspn(sha,"0123456789abcdef")!=64||!kind||
           (strcmp(kind,"BIN")&&strcmp(kind,"FLM"))||!integer(p,"size",FILE_LIMIT,&total)||!total){*code=400;*message="BIN/FLM kind, size and lowercase SHA256 required";goto done;}
        if(mkdir("/v4/WLINK",0700)&&errno!=EEXIST){*code=500;*message="Cannot create isolated WLINK directory";goto done;}
        char final[64],actual[65];size_t actual_size;
        snprintf(final,sizeof final,"/v4/WLINK/F%.7s.%s",sha,kind);
        struct stat st;
        if(!stat(final,&st)){
            if(!digest_file(final,actual,&actual_size)||actual_size!=total||strcmp(actual,sha)){
                *message="Content-name collision; existing file not overwritten";goto done;
            }
            result=cJSON_CreateObject();cJSON_AddBoolToObject(result,"complete",true);
            cJSON_AddStringToObject(result,"path",final+3);cJSON_AddStringToObject(result,"sha256",actual);goto done;
        }
        snprintf(upload.id,sizeof upload.id,"%08lx%08lx",(unsigned long)esp_random(),(unsigned long)esp_random());
        strcpy(upload.owner,owner);strcpy(upload.sha,sha);strcpy(upload.final,final);strcpy(upload.remote,final+3);upload.total=total;
        snprintf(upload.temporary,sizeof upload.temporary,"/v4/WLINK/T%.7s.TMP",upload.id);
        if(!stat(upload.temporary,&st)){memset(&upload,0,sizeof upload);*message="Temporary name collision; preserved";goto done;}
        upload.buffer=heap_caps_malloc(total,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
        if(!upload.buffer){memset(&upload,0,sizeof upload);*code=500;*message="Cannot allocate PSRAM staging buffer";goto done;}
        upload.file=fopen(upload.temporary,"wb");
        if(!upload.file){free(upload.buffer);memset(&upload,0,sizeof upload);*code=500;*message="Cannot open staging file";goto done;}
        result=cJSON_CreateObject();cJSON_AddBoolToObject(result,"complete",false);cJSON_AddStringToObject(result,"upload_id",upload.id);cJSON_AddNumberToObject(result,"offset",0);
    }else{
        const char *id=text(p,"upload_id");
        if(!id||!upload.id[0]||strcmp(id,upload.id)||strcmp(owner,upload.owner))goto done;
        if(!strcmp(method,"probe.files.abort")){abort_locked();result=cJSON_CreateObject();cJSON_AddBoolToObject(result,"aborted",true);}
        else if(!strcmp(method,"probe.files.write")){
            size_t offset,n=0;const char *encoded=text(p,"data_base64");
            if(!upload.file||!upload.buffer||!integer(p,"offset",FILE_LIMIT,&offset)||offset!=upload.offset||offset>=upload.total){*message="Upload offset mismatch; chunk not replayed";goto done;}
            size_t capacity=upload.total-upload.offset;if(capacity>2048)capacity=2048;
            if(!encoded||mbedtls_base64_decode(upload.buffer+upload.offset,capacity,&n,(const unsigned char*)encoded,strlen(encoded))||!n){*code=400;*message="Invalid bounded file chunk";goto done;}
            /* Acknowledgement means accepted into the owner-bound PSRAM
             * staging buffer. Only commit makes a verified disk file usable. */
            upload.offset+=n;result=cJSON_CreateObject();cJSON_AddNumberToObject(result,"offset",upload.offset);cJSON_AddBoolToObject(result,"buffered",true);
        }else if(!strcmp(method,"probe.files.commit")){
            if(!upload.file||!upload.buffer||upload.offset!=upload.total){*message="Upload incomplete; cannot commit";goto done;}
            unsigned char digest[32];char buffered_sha[65];
            if(mbedtls_sha256(upload.buffer,upload.total,digest,0)){*code=500;*message="Buffered SHA256 failed; no commit";goto done;}
            for(unsigned i=0;i<32;i++){snprintf(buffered_sha+2*i,3,"%02x",digest[i]);}
            buffered_sha[64]=0;
            if(strcmp(buffered_sha,upload.sha)){abort_locked();*code=400;*message="Buffered content hash mismatch; no commit";goto done;}
            if(fwrite(upload.buffer,1,upload.total,upload.file)!=upload.total){abort_locked();*code=500;*message="Partial staging flush; aborted, no replay";goto done;}
            int flushed=fflush(upload.file),synced=fsync(fileno(upload.file)),closed=fclose(upload.file);upload.file=NULL;
            free(upload.buffer);upload.buffer=NULL;
            char actual[65];size_t size;
            if(flushed||synced||closed||!digest_file(upload.temporary,actual,&size)||size!=upload.total||strcmp(actual,upload.sha)){
                *code=500;*message="Staging readback/SHA256 failed; file not committed";goto done;
            }
            struct stat st;
            if(!stat(upload.final,&st)||rename(upload.temporary,upload.final)){*code=500;*message="Atomic commit failed; existing file not overwritten";goto done;}
            result=cJSON_CreateObject();cJSON_AddStringToObject(result,"path",upload.remote);cJSON_AddStringToObject(result,"sha256",actual);cJSON_AddNumberToObject(result,"bytes",size);
            memset(&upload,0,sizeof upload);
        }else{*code=404;*message="Unsupported file method";}
    }
done:
    xSemaphoreGive(guard);return result;
}
