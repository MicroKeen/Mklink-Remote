#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "usb/usb_host.h"
#include "descriptor_check.h"
#include "usb_monitor.h"
#include "firmware_update.h"
#include "esp_psram.h"
#include "v4_backend.h"
#include "v4_storage.h"

#define V4_VID 0x0d28
#define V4_PID 0x0202
#define ADDRESS_COUNT 128

typedef struct {
    usb_device_handle_t handle;
    bool pending_open;
    bool gone;
} device_slot_t;

static portMUX_TYPE s_status_mux = portMUX_INITIALIZER_UNLOCKED;
static usb_monitor_status_t s_usb_status;
void usb_monitor_snapshot(usb_monitor_status_t *out) { portENTER_CRITICAL(&s_status_mux); *out=s_usb_status; portEXIT_CRITICAL(&s_status_mux); }

static const char *TAG = "n16r8_host";
/* Only app_main/client context accesses slots; callbacks run in handle_events.
 * The daemon task services only Host Library events, never these slots.
 */
static device_slot_t s_devices[ADDRESS_COUNT];
static usb_host_client_handle_t s_client;

static const char *speed_name(usb_speed_t speed)
{
    switch (speed) {
    case USB_SPEED_LOW: return "LOW_1.5Mbps";
    case USB_SPEED_FULL: return "FULL_12Mbps";
    case USB_SPEED_HIGH: return "HIGH_480Mbps";
    default: return "UNKNOWN";
    }
}

static void print_descriptor(const uint8_t *desc, int iface, int alt,
                             bool bulk_valid, void *arg)
{
    const unsigned address = *(const unsigned *)arg;
    if (desc[1] == 4) {
        ESP_LOGI(TAG, "USB_INTERFACE address=%u if=%d alt=%d class=%02x subclass=%02x protocol=%02x endpoints=%u",
                 address, iface, alt, desc[5], desc[6], desc[7], desc[4]);
    } else if (desc[1] == 5) {
        const unsigned raw_mps = desc[4] | ((unsigned)desc[5] << 8);
        static const char *types[] = {"CONTROL", "ISO", "BULK", "INTERRUPT"};
        ESP_LOGI(TAG, "USB_ENDPOINT address=%u if=%d alt=%d ep=%02x direction=%s type=%s mps=%u raw_mps=0x%04x interval=%u bulk_check=%s",
                 address, iface, alt, desc[2], desc[2] & 0x80 ? "IN" : "OUT",
                 types[desc[3] & 3], raw_mps & 0x7ff, raw_mps, desc[6],
                 (desc[3] & 3) != 2 ? "NA" : (bulk_valid ? "VALID" : "INVALID"));
    }
}

static void inspect_device(unsigned address, usb_device_handle_t handle)
{
    usb_device_info_t info;
    const usb_device_desc_t *device;
    const usb_config_desc_t *config;
    esp_err_t err = usb_host_device_info(handle, &info);
    if (err != ESP_OK) goto failed;
    err = usb_host_get_device_descriptor(handle, &device);
    if (err != ESP_OK) goto failed;
    err = usb_host_get_active_config_descriptor(handle, &config);
    if (err != ESP_OK) goto failed;

    const bool is_v4 = device->idVendor == V4_VID && device->idProduct == V4_PID;
    ESP_LOGI(TAG, "USB_DEVICE address=%u speed=%s vid=%04x pid=%04x expected_v4_id=%s bcdUSB=%04x ep0_mps=%u config_bytes=%u",
             address, speed_name(info.speed), device->idVendor, device->idProduct,
             is_v4 ? "YES" : "NO", device->bcdUSB, device->bMaxPacketSize0,
             config->wTotalLength);
    usb_print_device_descriptor(device);
    if (info.str_desc_manufacturer) {
        ESP_LOGI(TAG, "USB_MANUFACTURER address=%u", address);
        usb_print_string_descriptor(info.str_desc_manufacturer);
    }
    if (info.str_desc_product) {
        ESP_LOGI(TAG, "USB_PRODUCT address=%u", address);
        usb_print_string_descriptor(info.str_desc_product);
    }
    if (info.str_desc_serial_num) {
        ESP_LOGI(TAG, "USB_SERIAL address=%u", address);
        usb_print_string_descriptor(info.str_desc_serial_num);
    }
    if (config->wTotalLength > CONFIG_USB_HOST_CONTROL_TRANSFER_MAX_SIZE) {
        ESP_LOGE(TAG, "DESCRIPTOR_REJECT address=%u reason=config_too_large", address);
        return;
    }
    /* Cached configuration buffer belongs to IDF Host stack. It supplies the
     * buffer sized during enumeration; parser checks each contained descriptor.
     */
    descriptor_summary_t summary;
    const check_speed_t check_speed = info.speed == USB_SPEED_FULL ? CHECK_FULL_SPEED :
                                     info.speed == USB_SPEED_HIGH ? CHECK_HIGH_SPEED : CHECK_LOW_SPEED;
    const bool parsed = descriptor_check((const uint8_t *)config, config->wTotalLength,
                                         check_speed, &summary, print_descriptor, &address);
    portENTER_CRITICAL(&s_status_mux);
    s_usb_status=(usb_monitor_status_t){.connected=true,.vid=device->idVendor,.pid=device->idProduct,.speed=info.speed,.invalid_bulk=summary.invalid_bulk,.interfaces=summary.interfaces,.endpoints=summary.endpoints};
    portEXIT_CRITICAL(&s_status_mux);
    const bool command_shape = summary.command_control_if4 && summary.command_data_if5 &&
                               summary.command_out07 && summary.command_in87;
    ESP_LOGI(TAG, "ENUM_RESULT address=%u structure=%s interface_descriptors=%u endpoints=%u invalid_bulk=%u v4_command_shape=%s",
             address, parsed ? "OK" : "INVALID", summary.interfaces, summary.endpoints,
             summary.invalid_bulk, command_shape ? "MATCH" : "NO_MATCH");
    if (!parsed || summary.invalid_bulk) {
        ESP_LOGW(TAG, "DESCRIPTOR_WARNING address=%u reason=%s no_interface_claimed=1",
                 address, !parsed ? "malformed_configuration" : "bulk_mps_incompatible_with_speed");
    }
    if(is_v4 && parsed && !summary.invalid_bulk && command_shape){
        v4_backend_attach(address,handle);
        v4_storage_attach(address);
    }
    return;
failed:
    ESP_LOGW(TAG, "INSPECT_FAILED address=%u error=%s", address, esp_err_to_name(err));
}

static void client_event(const usb_host_client_event_msg_t *event, void *arg)
{
    (void)arg;
    /* No blocking, descriptor output, or device operations in this callback. */
    if (event->event == USB_HOST_CLIENT_EVENT_NEW_DEV) {
        const unsigned address = event->new_dev.address;
        if (address > 0 && address < ADDRESS_COUNT) s_devices[address].pending_open = true;
    } else if (event->event == USB_HOST_CLIENT_EVENT_DEV_GONE) {
        for (unsigned i = 1; i < ADDRESS_COUNT; ++i) {
            if (s_devices[i].handle == event->dev_gone.dev_hdl) s_devices[i].gone = true;
        }
    }
}

static void process_devices(void)
{
    for (unsigned address = 1; address < ADDRESS_COUNT; ++address) {
        device_slot_t *slot = &s_devices[address];
        if (slot->gone) {
            v4_backend_detach(address);
            v4_storage_detach();
            const esp_err_t err = usb_host_device_close(s_client, slot->handle);
            if (err != ESP_OK) {
                ESP_LOGE(TAG, "USB_CLOSE_FAILED address=%u error=%s", address, esp_err_to_name(err));
                continue; /* Retain the handle and retry instead of losing ownership. */
            }
            slot->handle = NULL;
            slot->gone = false;
            portENTER_CRITICAL(&s_status_mux); s_usb_status.connected=false; portEXIT_CRITICAL(&s_status_mux);
            ESP_LOGI(TAG, "USB_DISCONNECTED address=%u", address);
        }
        if (slot->pending_open && !slot->handle) {
            slot->pending_open = false;
            const esp_err_t err = usb_host_device_open(s_client, address, &slot->handle);
            if (err != ESP_OK) {
                slot->handle = NULL;
                ESP_LOGW(TAG, "USB_OPEN_FAILED address=%u error=%s", address, esp_err_to_name(err));
                continue;
            }
            inspect_device(address, slot->handle);
        }
    }
}

static void daemon_task(void *arg)
{
    (void)arg;
    for (;;) {
        uint32_t flags = 0;
        const esp_err_t err = usb_host_lib_handle_events(portMAX_DELAY, &flags);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "HOST_EVENT_ERROR error=%s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        /* Client remains registered for the lifetime of this diagnostic app. */
    }
}

void usb_monitor_task(void *arg)
{
    (void)arg;
    const esp_app_desc_t *app = esp_app_get_description();
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    uint32_t flash_bytes = 0;
    const esp_err_t flash_err = esp_flash_get_physical_size(NULL, &flash_bytes);
    ESP_LOGI(TAG, "APP board=third-party-esp32-s3-n16r8 project=%s version=%s idf=%s",
             app->project_name, app->version, esp_get_idf_version());
    ESP_LOGI(TAG, "CHIP revision=%u cores=%u flash_physical_bytes=%" PRIu32 " flash_query=%s psram_bytes=%u reset_reason=%d",
             chip.revision, chip.cores, flash_bytes, esp_err_to_name(flash_err), (unsigned)esp_psram_get_size(), esp_reset_reason());
    /* Hardware source: vendor/ESP32-S3-SCH.pdf page 1:
     * USB1 -> CH343P -> UART0; USB2 -> GPIO19(D-)/20(D+).
     * USB-OTG jumper bypasses D2. No software VBUS enable/fault pins exist.
     * Do not import the official OTG PCB's GPIO18/13/12/17/21 controls.
     */
    ESP_LOGI(TAG, "WIRING console=USB1_CH343_UART0 baud=115200 USB2_DM=19 USB2_DP=20");
    ESP_LOGW(TAG, "VBUS source=USB1_via_D1_and_USB_OTG_jumper control=HARDWARE_ONLY voltage=NOT_MEASURED");
    ESP_LOGI(TAG, "MODE guarded_native_cdc expected_v4=%04x:%04x", V4_VID, V4_PID);

    const usb_host_config_t host = {.skip_phy_setup = false, .intr_flags = ESP_INTR_FLAG_LEVEL1};
    ESP_ERROR_CHECK(usb_host_install(&host));
    const usb_host_client_config_t client = {
        .is_synchronous = false,
        .max_num_event_msg = 16,
        .async = {.client_event_callback = client_event, .callback_arg = NULL},
    };
    ESP_ERROR_CHECK(usb_host_client_register(&client, &s_client));
    ESP_ERROR_CHECK(v4_backend_start());
    ESP_ERROR_CHECK(v4_storage_start());
    /* Register before servicing Host events, so a V4 present at power-on cannot
     * enumerate before this client exists and lose its NEW_DEV notification.
     */
    if (xTaskCreate(daemon_task, "usb_daemon", 4096, NULL, 3, NULL) != pdPASS) {
        ESP_LOGE(TAG, "TASK_CREATE_FAILED usb_daemon");
        ESP_ERROR_CHECK(usb_host_client_deregister(s_client));
        ESP_ERROR_CHECK(usb_host_uninstall());
        return;
    }
    ESP_LOGI(TAG, "HOST_READY connect_V4_to_USB2; logs_remain_on_USB1");
    firmware_update_health_ready();
    int64_t next_heartbeat = esp_timer_get_time() + 5000000;
    for (;;) {
        const esp_err_t err = usb_host_client_handle_events(s_client, pdMS_TO_TICKS(250));
        if (err != ESP_OK && err != ESP_ERR_TIMEOUT) {
            ESP_LOGE(TAG, "CLIENT_EVENT_ERROR error=%s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        process_devices();
        const int64_t now = esp_timer_get_time();
        if (now >= next_heartbeat) {
            unsigned opened = 0;
            for (unsigned i = 1; i < ADDRESS_COUNT; ++i) opened += s_devices[i].handle != NULL;
            ESP_LOGI(TAG, "HEARTBEAT uptime_ms=%" PRId64 " open_devices=%u free_heap=%" PRIu32,
                     now / 1000, opened, esp_get_free_heap_size());
            next_heartbeat = now + 5000000;
        }
    }
}
