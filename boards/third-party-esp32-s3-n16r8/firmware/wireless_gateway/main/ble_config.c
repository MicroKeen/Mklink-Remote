/* BLE configuration, not Classic SPP. Same RPC/control gate as USB and HTTP.
 * App-level authenticated encryption: HKDF-like HMAC session key from the USB
 * management secret + fresh per-connection challenge; AES-128-GCM and strict
 * monotonic sequence. No plaintext passwords/tokens and no OS bond changes.
 * APIs follow ESP-IDF 5.5.2 nimble/bleprph and NimBLE GATT server examples. */
#include "ble_config.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "mbedtls/gcm.h"
#include "mbedtls/md.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include <stdlib.h>
#include <string.h>
#define RX_LIMIT 4608
#define REPLY_LIMIT 65503 /* uint16 frame total includes32 bytes of AEAD envelope. */
#define UUID_BYTES(n)                                                                                        \
    0x01, 0x44, 0x54, 0x0a, 0x79, 0xe4, 0x4b, 0x8b, 0x4d, 0x4c, 0x63, 0x4c, n, 0x00, 0xf5, 0x9a
static const ble_uuid128_t svc_uuid = BLE_UUID128_INIT(UUID_BYTES(1));
static const ble_uuid128_t rx_uuid = BLE_UUID128_INIT(UUID_BYTES(2));
static const ble_uuid128_t tx_uuid = BLE_UUID128_INIT(UUID_BYTES(3));
static const ble_uuid128_t info_uuid = BLE_UUID128_INIT(UUID_BYTES(4));
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static ble_config_status_t status;
static QueueHandle_t jobs;
static uint16_t connection = BLE_HS_CONN_HANDLE_NONE, tx_handle;
static uint8_t challenge[16], own_address_type;
static uint32_t generation, expected_sequence = 1;
static uint8_t *rx,*reply_packet;
static uint16_t rx_id, rx_total, rx_used;
typedef struct {
    uint16_t conn, id, length;
    uint32_t generation;
    uint8_t salt[16];
    uint8_t payload[];
} job_t;
static uint16_t u16(const uint8_t *p) { return p[0] | ((uint16_t)p[1] << 8); }
static uint32_t u32(const uint8_t *p) {
    return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static void put16(uint8_t *p, unsigned n) {
    p[0] = n;
    p[1] = n >> 8;
}
static void put32(uint8_t *p, uint32_t n) {
    p[0] = n;
    p[1] = n >> 8;
    p[2] = n >> 16;
    p[3] = n >> 24;
}
void ble_config_snapshot(ble_config_status_t *out) {
    portENTER_CRITICAL(&mux);
    *out = status;
    portEXIT_CRITICAL(&mux);
}
static bool same_session(const job_t *j) {
    portENTER_CRITICAL(&mux);
    bool same = connection == j->conn && generation == j->generation;
    portEXIT_CRITICAL(&mux);
    return same;
}
static int access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctx, void *arg) {
    (void)attr;
    (void)arg;
    if (ble_uuid_cmp(ctx->chr->uuid, &info_uuid.u) == 0) {
        uint8_t data[17] = {1};
        portENTER_CRITICAL(&mux);
        memcpy(data + 1, challenge, 16);
        portEXIT_CRITICAL(&mux);
        return os_mbuf_append(ctx->om, data, sizeof(data)) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    if (ctx->op != BLE_GATT_ACCESS_OP_WRITE_CHR)
        return BLE_ATT_ERR_READ_NOT_PERMITTED;
    uint8_t frame[256];
    uint16_t length = 0;
    if (ble_hs_mbuf_to_flat(ctx->om, frame, sizeof(frame), &length) != 0 || length < 7)
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    uint16_t id = u16(frame), offset = u16(frame + 2), total = u16(frame + 4);
    if (total < 33 || total > RX_LIMIT || offset + (length - 6) > total)
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    if (offset == 0) {
        rx_id = id;
        rx_total = total;
        rx_used = 0;
    }
    if (id != rx_id || total != rx_total || offset != rx_used)
        return BLE_ATT_ERR_UNLIKELY;
    memcpy(rx + rx_used, frame + 6, length - 6);
    rx_used += length - 6;
    if (rx_used == rx_total) {
        job_t *j = heap_caps_malloc(sizeof(*j) + rx_total,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
        if (!j)
            return BLE_ATT_ERR_INSUFFICIENT_RES;
        j->conn = conn;
        j->id = id;
        j->length = rx_total;
        portENTER_CRITICAL(&mux);
        j->generation = generation;
        memcpy(j->salt, challenge, 16);
        portEXIT_CRITICAL(&mux);
        memcpy(j->payload, rx, rx_total);
        rx_used = 0;
        if (xQueueSend(jobs, &j, 0) != pdTRUE) {
            free(j);
            return BLE_ATT_ERR_INSUFFICIENT_RES;
        }
    }
    return 0;
}
static const struct ble_gatt_svc_def services[] = {
    {.type = BLE_GATT_SVC_TYPE_PRIMARY,
     .uuid = &svc_uuid.u,
     .characteristics =
         (struct ble_gatt_chr_def[]){
             {.uuid = &rx_uuid.u, .access_cb = access, .flags = BLE_GATT_CHR_F_WRITE},
             {.uuid = &tx_uuid.u,
              .access_cb = access,
              .flags = BLE_GATT_CHR_F_NOTIFY,
              .val_handle = &tx_handle},
             {.uuid = &info_uuid.u, .access_cb = access, .flags = BLE_GATT_CHR_F_READ},
             {0}}},
    {0}};
static void advertise(void);
static int gap_event(struct ble_gap_event *event, void *arg) {
    (void)arg;
    if (event->type == BLE_GAP_EVENT_CONNECT) {
        if (event->connect.status == 0) {
            uint8_t salt[16];
            esp_fill_random(salt, sizeof(salt));
            portENTER_CRITICAL(&mux);
            connection = event->connect.conn_handle;
            generation++;
            expected_sequence = 1;
            memcpy(challenge, salt, 16);
            status.connected = true;
            portEXIT_CRITICAL(&mux);
            rx_used = 0;
        } else
            advertise();
    } else if (event->type == BLE_GAP_EVENT_DISCONNECT) {
        portENTER_CRITICAL(&mux);
        connection = BLE_HS_CONN_HANDLE_NONE;
        generation++;
        status.connected = false;
        portEXIT_CRITICAL(&mux);
        rx_used = 0;
        advertise();
    } else if (event->type == BLE_GAP_EVENT_ADV_COMPLETE)
        advertise();
    return 0;
}
static void advertise(void) {
    struct ble_hs_adv_fields fields = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128 = (ble_uuid128_t *)&svc_uuid;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    if (ble_gap_adv_set_fields(&fields) != 0)
        return;
    memset(&fields, 0, sizeof(fields));
    const char *name = ble_svc_gap_device_name();
    fields.name = (uint8_t *)name;
    fields.name_len = strlen(name);
    fields.name_is_complete = 1;
    ble_gap_adv_rsp_set_fields(&fields);
    struct ble_gap_adv_params p = {0};
    p.conn_mode = BLE_GAP_CONN_MODE_UND;
    p.disc_mode = BLE_GAP_DISC_MODE_GEN;
    ble_gap_adv_start(own_address_type, NULL, BLE_HS_FOREVER, &p, gap_event, NULL);
}
static void sync_host(void) {
    if (ble_hs_id_infer_auto(0, &own_address_type) == 0)
        advertise();
}
static void host_task(void *arg) {
    (void)arg;
    nimble_port_run();
    nimble_port_freertos_deinit();
}
static bool crypt(job_t *j, uint8_t session_key[16], char **plain, uint32_t *sequence) {
    uint8_t key[16], material[29], digest[32];
    config_ble_key(key);
    memcpy(material, "MKLINK-BLE-v1", 13);
    memcpy(material + 13, j->salt, 16);
    if (mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, sizeof(key), material,
                        sizeof(material), digest) != 0)
        return false;
    memcpy(session_key, digest, 16);
    memset(key, 0, sizeof(key));
    memset(digest, 0, sizeof(digest));
    *sequence = u32(j->payload);
    portENTER_CRITICAL(&mux);
    bool expected = *sequence == expected_sequence && generation == j->generation && connection == j->conn;
    portEXIT_CRITICAL(&mux);
    if (!expected)
        return false;
    size_t length = j->length - 32;
    char *out = heap_caps_calloc(1, length + 1,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if (!out)
        return false;
    uint8_t aad[25];
    memcpy(aad, "mklink-ble-request-v1", 21);
    put32(aad + 21, *sequence);
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, session_key, 128);
    int rc = mbedtls_gcm_auth_decrypt(&gcm, length, j->payload + 4, 12, aad, sizeof(aad),
                                      j->payload + j->length - 16, 16, j->payload + 16, (uint8_t *)out);
    mbedtls_gcm_free(&gcm);
    if (rc || memchr(out, 0, length)) {
        free(out);
        return false;
    }
    portENTER_CRITICAL(&mux);
    if (generation != j->generation || connection != j->conn) {
        portEXIT_CRITICAL(&mux);
        free(out);
        return false;
    }
    expected_sequence++;
    status.requests++;
    status.last_request_sequence=*sequence;
    portEXIT_CRITICAL(&mux);
    *plain = out;
    return true;
}
static void reply(job_t *j, const uint8_t key[16], uint32_t sequence, const char *text) {
    size_t length = strlen(text);
    if (length > REPLY_LIMIT) {
        portENTER_CRITICAL(&mux);status.reply_alloc_failures++;portEXIT_CRITICAL(&mux);
        return;
    }
    uint8_t *packet=reply_packet; /* One worker owns this reusable PSRAM buffer. */
    put32(packet, sequence);
    esp_fill_random(packet + 4, 12);
    uint8_t aad[26];
    memcpy(aad, "mklink-ble-response-v1", 22);
    put32(aad + 22, sequence);
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    int rc=mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key, 128);
    if(!rc)rc = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, length, packet + 4, 12, aad, sizeof(aad),
                                       (uint8_t *)text, packet + 16, 16, packet + 16 + length);
    mbedtls_gcm_free(&gcm);
    if (!rc) {
        unsigned mtu = ble_att_mtu(j->conn);
        unsigned chunk = mtu > 9 ? mtu - 9 : 14;
        if (chunk > 180)
            chunk = 180;
        for (unsigned offset = 0; offset < length + 32 && same_session(j);) {
            unsigned n = length + 32 - offset;
            if (n > chunk)
                n = chunk;
            uint8_t frame[186];
            put16(frame, j->id);
            put16(frame + 2, offset);
            put16(frame + 4, length + 32);
            memcpy(frame + 6, packet + offset, n);
            int error=BLE_HS_ENOMEM;int64_t deadline=esp_timer_get_time()+1000000;
            do {
                struct os_mbuf *om=ble_hs_mbuf_from_flat(frame,n+6);
                /* NimBLE consumes om on both success/failure. Rebuild only
                 * frames which were NOT enqueued; never repeat a successful
                 * notification or an RPC/native target command. */
                error=om?ble_gatts_notify_custom(j->conn,tx_handle,om):BLE_HS_ENOMEM;
                if(!error)break;
                portENTER_CRITICAL(&mux);status.last_notify_error=error;status.notify_retries++;portEXIT_CRITICAL(&mux);
                if(error!=BLE_HS_ENOMEM&&error!=BLE_HS_EAGAIN&&error!=BLE_HS_EBUSY)break;
                vTaskDelay(pdMS_TO_TICKS(12));
            }while(same_session(j)&&esp_timer_get_time()<deadline);
            if(error){portENTER_CRITICAL(&mux);status.notify_failures++;portEXIT_CRITICAL(&mux);break;}
            portENTER_CRITICAL(&mux);status.notify_fragments++;portEXIT_CRITICAL(&mux);
            offset += n;
            if(offset==length+32){portENTER_CRITICAL(&mux);status.last_reply_sequence=sequence;status.last_reply_bytes=length+32;portEXIT_CRITICAL(&mux);}
            vTaskDelay(pdMS_TO_TICKS(12));
        }
    }else{
        portENTER_CRITICAL(&mux);status.reply_crypto_failures++;portEXIT_CRITICAL(&mux);
    }
    memset(packet, 0, length + 32);
}
static void worker(void *arg) {
    (void)arg;
    job_t *j;
    for (;;)
        if (xQueueReceive(jobs, &j, portMAX_DELAY) == pdTRUE) {
            uint8_t key[16] = {0};
            uint32_t seq;
            char *plain = NULL;
            if (same_session(j) && crypt(j, key, &plain, &seq)) {
                char *response = config_ble_rpc(plain);
                free(plain);
                if (response) {
                    reply(j, key, seq, response);
                    free(response);
                }else{portENTER_CRITICAL(&mux);status.rpc_response_failures++;portEXIT_CRITICAL(&mux);}
            } else {
                portENTER_CRITICAL(&mux);
                status.auth_failures++;
                portEXIT_CRITICAL(&mux);
            }
            memset(key, 0, sizeof(key));
            memset(j->payload, 0, j->length);
            free(j);
        }
}
esp_err_t ble_config_start(const char *name) {
    rx=heap_caps_malloc(RX_LIMIT,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    reply_packet=heap_caps_malloc(REPLY_LIMIT+32,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!rx||!reply_packet)return ESP_ERR_NO_MEM;
    jobs = xQueueCreate(1, sizeof(job_t *));
    if (!jobs)
        return ESP_ERR_NO_MEM;
    esp_err_t err = nimble_port_init();
    if (err != ESP_OK)
        return err;
    ble_hs_cfg.sync_cb = sync_host;
    ble_svc_gap_init();
    ble_svc_gatt_init();
    int rc = ble_gatts_count_cfg(services);
    if (!rc)
        rc = ble_gatts_add_svcs(services);
    if (rc)
        return ESP_FAIL;
    ble_svc_gap_device_name_set(name);
    ble_att_set_preferred_mtu(247);
    nimble_port_freertos_init(host_task);
    if (xTaskCreate(worker, "ble_rpc", 8192, NULL, 3, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;
    status.enabled = true;
    return ESP_OK;
}
