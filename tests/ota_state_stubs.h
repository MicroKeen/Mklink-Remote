/* Host-only platform doubles. Crypto/base64 are replaced to test state and
 * flash side effects; this suite does not qualify their algorithms. */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "cJSON.h"
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM 0x101
#define ESP_ERR_INVALID_CRC 0x109
#define ESP_ERR_INVALID_ARG 0x102
typedef void *SemaphoreHandle_t;
#define portMAX_DELAY 0xffffffff
#define pdPASS 1
#define pdMS_TO_TICKS(n) (n)
static inline SemaphoreHandle_t xSemaphoreCreateMutex(void){return (void*)1;}
static inline int xSemaphoreTake(SemaphoreHandle_t s,unsigned t){(void)s;(void)t;return 1;}
static inline int xSemaphoreGive(SemaphoreHandle_t s){(void)s;return 1;}
static inline int xTaskCreate(void(*f)(void*),const char*n,unsigned s,void*a,unsigned p,void*h){(void)f;(void)n;(void)s;(void)a;(void)p;(void)h;return 1;}
static inline void vTaskDelay(unsigned t){(void)t;}
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define MALLOC_CAP_SPIRAM 4
static inline void *heap_caps_malloc(size_t n,unsigned c){(void)c;return malloc(n);}
typedef struct {uint32_t magic_word;char project_name[32],version[32];} esp_app_desc_t;
typedef struct {uint8_t magic;uint16_t chip_id;} esp_image_header_t;
typedef struct {uint32_t address,size;} esp_image_segment_header_t;
#define ESP_APP_DESC_MAGIC_WORD 0xabcd5432
#define ESP_IMAGE_HEADER_MAGIC 0xe9
#define ESP_CHIP_ID_ESP32S3 9
typedef struct {uint32_t address,size;unsigned type,subtype;char label[16];} esp_partition_t;
#define ESP_PARTITION_TYPE_APP 0
#define ESP_PARTITION_SUBTYPE_APP_OTA_MIN 16
#define ESP_PARTITION_SUBTYPE_APP_OTA_MAX 32
typedef unsigned esp_ota_handle_t;
typedef enum {ESP_OTA_IMG_NEW=0,ESP_OTA_IMG_PENDING_VERIFY=1,ESP_OTA_IMG_VALID=2,ESP_OTA_IMG_INVALID=3,ESP_OTA_IMG_ABORTED=4,ESP_OTA_IMG_UNDEFINED=-1} esp_ota_img_states_t;
#define ESP_PARTITION_SUBTYPE_ANY 255
typedef void *esp_partition_iterator_t;
static inline esp_partition_iterator_t esp_partition_find(unsigned t,unsigned s,const char*n){(void)t;(void)s;(void)n;return NULL;}
static inline const esp_partition_t *esp_partition_get(esp_partition_iterator_t i){(void)i;return NULL;}
static inline esp_partition_iterator_t esp_partition_next(esp_partition_iterator_t i){(void)i;return NULL;}
static inline void esp_partition_iterator_release(esp_partition_iterator_t i){(void)i;}
typedef unsigned nvs_handle_t;
typedef struct {uint8_t bytes[32];size_t offset;} mbedtls_sha256_context;
extern unsigned mock_begin_calls,mock_write_calls,mock_end_calls,mock_boot_calls,mock_confirm_calls;
extern uint8_t mock_image[1024],mock_flash[4096];
extern size_t mock_decode_bytes;
extern esp_partition_t mock_factory,mock_ota,mock_current;
extern esp_ota_img_states_t mock_boot_state;
extern bool mock_corrupt_readback;
static inline int64_t esp_timer_get_time(void){return 1000000;}
static inline const char *esp_err_to_name(esp_err_t e){return e==ESP_OK?"ESP_OK":"MOCK_ERROR";}
static inline void esp_restart(void){}
static inline const esp_app_desc_t *esp_app_get_description(void){static esp_app_desc_t d={.version="0.6.2"};return &d;}
static inline const esp_partition_t *esp_ota_get_running_partition(void){return &mock_current;}
static inline const esp_partition_t *esp_ota_get_next_update_partition(const esp_partition_t*p){(void)p;return &mock_ota;}
static inline esp_err_t esp_ota_begin(const esp_partition_t*p,size_t n,esp_ota_handle_t*h){if(p->address==mock_current.address||n>sizeof mock_flash)abort();mock_begin_calls++;memset(mock_flash,255,sizeof mock_flash);*h=1;return ESP_OK;}
static inline esp_err_t esp_ota_write(esp_ota_handle_t h,const void*p,size_t n){(void)h;memcpy(mock_flash,p,n);mock_write_calls++;return ESP_OK;}
static inline esp_err_t esp_ota_end(esp_ota_handle_t h){(void)h;mock_end_calls++;return ESP_OK;}
static inline esp_err_t esp_ota_abort(esp_ota_handle_t h){(void)h;return ESP_OK;}
static inline esp_err_t esp_partition_read(const esp_partition_t*p,size_t o,void*b,size_t n){if(p->address==mock_current.address)abort();memcpy(b,mock_flash+o,n);if(mock_corrupt_readback)((uint8_t*)b)[0]^=1;return ESP_OK;}
static inline esp_err_t esp_ota_set_boot_partition(const esp_partition_t*p){if(p->address==mock_current.address)abort();mock_boot_calls++;return ESP_OK;}
static inline esp_err_t esp_ota_get_state_partition(const esp_partition_t*p,esp_ota_img_states_t*s){(void)p;*s=mock_boot_state;return ESP_OK;}
static inline esp_err_t esp_ota_mark_app_valid_cancel_rollback(void){mock_confirm_calls++;return ESP_OK;}
static inline esp_err_t esp_ota_mark_app_invalid_rollback_and_reboot(void){return ESP_FAIL;}
static inline esp_err_t nvs_open(const char*n,unsigned m,nvs_handle_t*h){(void)n;(void)m;*h=1;return ESP_OK;}
#define NVS_READWRITE 1
static inline esp_err_t nvs_get_blob(nvs_handle_t h,const char*k,void*b,size_t*n){(void)h;(void)k;(void)b;(void)n;return ESP_FAIL;}
static inline esp_err_t nvs_set_blob(nvs_handle_t h,const char*k,const void*b,size_t n){(void)h;(void)k;(void)b;(void)n;return ESP_OK;}
static inline esp_err_t nvs_commit(nvs_handle_t h){(void)h;return ESP_OK;}
static inline void mbedtls_sha256_init(mbedtls_sha256_context*h){memset(h,0,sizeof *h);}
static inline int mbedtls_sha256_starts(mbedtls_sha256_context*h,int x){(void)x;memset(h,0,sizeof *h);return 0;}
static inline int mbedtls_sha256_update(mbedtls_sha256_context*h,const unsigned char*b,size_t n){for(size_t i=0;i<n;i++)h->bytes[h->offset++%32]^=b[i];return 0;}
static inline int mbedtls_sha256_finish(mbedtls_sha256_context*h,unsigned char*d){memcpy(d,h->bytes,32);return 0;}
static inline void mbedtls_sha256_free(mbedtls_sha256_context*h){(void)h;}
static inline int mbedtls_sha256(const unsigned char*b,size_t n,unsigned char*d,int x){mbedtls_sha256_context h;mbedtls_sha256_starts(&h,x);mbedtls_sha256_update(&h,b,n);return mbedtls_sha256_finish(&h,d);}
static inline int mbedtls_base64_decode(unsigned char*b,size_t cap,size_t*n,const unsigned char*s,size_t len){(void)s;(void)len;if(mock_decode_bytes>cap)return -1;memcpy(b,mock_image,mock_decode_bytes);*n=mock_decode_bytes;return 0;}
