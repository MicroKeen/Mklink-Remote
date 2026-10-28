#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "config_service.h"
#include "usb_monitor.h"
#include "gateway_memory.h"
void app_main(void) {
    ESP_ERROR_CHECK(gateway_memory_init());
    ESP_ERROR_CHECK(config_service_start());
    if(xTaskCreate(usb_monitor_task,"usb_client",8192,NULL,4,NULL)!=pdPASS) {
        ESP_LOGE("gateway","USB task creation failed");
        return;
    }
}
