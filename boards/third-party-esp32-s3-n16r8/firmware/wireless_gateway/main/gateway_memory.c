#include "gateway_memory.h"
#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_psram.h"
#include <stdlib.h>
static void *json_external_alloc(size_t bytes) {
    return heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
}
esp_err_t gateway_memory_init(void) {
    /* This profile is specifically N16R8. IDF initializes and memory-tests
     * octal PSRAM before app_main; never silently fall back to a tiny heap. */
    if(!esp_psram_is_initialized()||esp_psram_get_size()<8*1024*1024)return ESP_ERR_NOT_FOUND;
    cJSON_Hooks hooks={.malloc_fn=json_external_alloc,.free_fn=free};
    cJSON_InitHooks(&hooks); /* Set once, before any application task/JSON use. */
    ESP_LOGI("memory","PSRAM_READY bytes=%u internal_free=%u",(unsigned)esp_psram_get_size(),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
    return ESP_OK;
}
