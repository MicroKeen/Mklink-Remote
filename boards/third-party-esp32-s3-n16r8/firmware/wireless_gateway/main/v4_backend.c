/* Pinned CDC host API: espressif/usb_host_cdc_acm 2.4.1.
 * Board USB2 = GPIO19/20; no official-board VBUS GPIO is used here.
 * This backend completes bounded REPL lines at a complete prompt. It does not
 * implement binary streaming (RTT/MUX/YMODEM), nor claim target-operation success.
 */
#include "v4_backend.h"
#include "config_service.h"
#include "probe_protocol.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"
#include "usb/cdc_acm_host.h"
#include <stdio.h>
#include <string.h>
#define RX_BYTES (3U*1024U*1024U)
#define GONE BIT0
#define IO_ERROR BIT1
#define OVERFLOW BIT2
#define FAULTS (GONE | IO_ERROR | OVERFLOW)
static const char *TAG="v4_backend";
static SemaphoreHandle_t access;
static EventGroupHandle_t events;
static StreamBufferHandle_t rx;
static StaticStreamBuffer_t rx_control;
static uint8_t *rx_storage;
static mklink_reply_t *response;
static cdc_acm_dev_hdl_t cdc;
static portMUX_TYPE status_mux=portMUX_INITIALIZER_UNLOCKED;
static v4_backend_status_t status={.state="not_connected"};
void v4_backend_metrics_reset(void){
    portENTER_CRITICAL(&status_mux);
    status.measure_rx_bytes=status.measure_tx_bytes=0;
    status.measure_first_rx_us=status.measure_last_rx_us=status.measure_tx_start_us=0;
    status.measure_start_us=esp_timer_get_time();
    portEXIT_CRITICAL(&status_mux);
}

void v4_backend_snapshot(v4_backend_status_t *out){
    portENTER_CRITICAL(&status_mux);*out=status;portEXIT_CRITICAL(&status_mux);
    out->rx_pending=rx?xStreamBufferBytesAvailable(rx):0;out->rx_capacity=RX_BYTES;
    if(events&&!strcmp(out->state,"ready")&&(xEventGroupGetBits(events)&FAULTS)){
        strcpy(out->state,"quarantined");
        snprintf(out->error,sizeof out->error,"USB disconnected or failed; reconnect USB2 before reuse");
    }
}
static void state(const char *name,const char *error){
    portENTER_CRITICAL(&status_mux);
    snprintf(status.state,sizeof status.state,"%s",name);
    snprintf(status.error,sizeof status.error,"%s",error?error:"");
    portEXIT_CRITICAL(&status_mux);
}
static bool receive(const uint8_t *data,size_t bytes,void *arg){
    (void)arg;
    const bool overflow=xStreamBufferSend(rx,data,bytes,0)!=bytes;
    const unsigned pending=xStreamBufferBytesAvailable(rx);
    portENTER_CRITICAL(&status_mux);
    if(status.measure_start_us&&bytes){
        if(!status.measure_first_rx_us)status.measure_first_rx_us=esp_timer_get_time();
        status.measure_last_rx_us=esp_timer_get_time();status.measure_rx_bytes+=bytes;
    }
    if(pending>status.rx_peak)status.rx_peak=pending;
    if(overflow)status.rx_overflows++;
    portEXIT_CRITICAL(&status_mux);
    if(overflow)xEventGroupSetBits(events,OVERFLOW);
    return true;
}
static void event(const cdc_acm_host_dev_event_data_t *e,void *arg){
    (void)arg;
    if(e->type==CDC_ACM_HOST_DEVICE_DISCONNECTED)xEventGroupSetBits(events,GONE);
    else if(e->type==CDC_ACM_HOST_ERROR)xEventGroupSetBits(events,IO_ERROR);
}
static bool failed(void){return (xEventGroupGetBits(events)&FAULTS)!=0;}
static probe_result_t uncertain(const char *why){state("quarantined",why);return PROBE_OUTCOME_UNKNOWN;}

/* access is held throughout. No callback takes access or the node RPC lock. */
static probe_result_t exchange_locked(const uint8_t *request,size_t bytes,uint8_t *reply,
                                     size_t capacity,size_t *written,unsigned timeout){
    *written=0;
    if(!cdc||failed())return PROBE_NOT_READY;
    if(!bytes||bytes>511||request[bytes-1]!='\n'||memchr(request,0,bytes)||
       memchr(request,'\n',bytes-1))return PROBE_INVALID;
    uint8_t chunk[256];
    TickType_t started=xTaskGetTickCount();
    /* Reject an active stream instead of injecting a command into it. */
    while(xStreamBufferReceive(rx,chunk,sizeof chunk,pdMS_TO_TICKS(40))){
        if(failed())return PROBE_NOT_READY;
        if(xTaskGetTickCount()-started>=pdMS_TO_TICKS(250)){
            state("quarantined","Unexpected active stream; reconnect USB2 before reuse");
            return PROBE_OUTCOME_UNKNOWN;
        }
    }
    if(failed())return PROBE_NOT_READY;
    mklink_reply_reset(response);
    /* A TX error may occur after partial delivery. Never retry this write. */
    TickType_t elapsed=xTaskGetTickCount()-started;
    if(elapsed>=pdMS_TO_TICKS(timeout))return PROBE_NOT_READY;
    unsigned remaining=(pdMS_TO_TICKS(timeout)-elapsed)*portTICK_PERIOD_MS;
    esp_err_t err=cdc_acm_host_data_tx_blocking(cdc,request,bytes,remaining?remaining:1);
    if(err!=ESP_OK)return uncertain("USB transmit outcome unknown; do not replay");
    while(xTaskGetTickCount()-started<pdMS_TO_TICKS(timeout)){
        if(failed())return uncertain("USB disconnected, overflowed or failed after transmit");
        size_t count=xStreamBufferReceive(rx,chunk,sizeof chunk,pdMS_TO_TICKS(20));
        if(count&&!mklink_reply_feed(response,chunk,count))return uncertain("Reply overflow or unexpected binary stream");
        if(mklink_reply_prompt(response)){
            if(failed())return uncertain("USB failed at reply completion");
            if(response->length>capacity)return uncertain("Complete reply exceeds RPC capacity");
            memmove(reply,response->data,response->length);*written=response->length;return PROBE_OK;
        }
    }
    return uncertain("Reply prompt not completed before deadline; do not replay");
}
static probe_result_t exchange(void *context,const uint8_t *request,size_t bytes,uint8_t *reply,
                               size_t capacity,size_t *written,unsigned timeout){
    (void)context;
    if(xSemaphoreTake(access,0)!=pdTRUE)return PROBE_NOT_READY;
    v4_backend_status_t current;v4_backend_snapshot(&current);
    probe_result_t result=!strcmp(current.state,"quarantined")?PROBE_OUTCOME_UNKNOWN:
        exchange_locked(request,bytes,reply,capacity,written,timeout);
    xSemaphoreGive(access);return result;
}
static probe_result_t stream(void *context,probe_stream_op_t op,const uint8_t *in,size_t n,
                             uint8_t *out,size_t cap,size_t *written){
    (void)context;*written=0;
    if(xSemaphoreTake(access,0)!=pdTRUE)return PROBE_NOT_READY;
    probe_result_t rc=PROBE_OK;
    v4_backend_status_t current;v4_backend_snapshot(&current);
    if(!strcmp(current.state,"quarantined")||failed())rc=PROBE_OUTCOME_UNKNOWN;
    else if(!cdc||strcmp(current.state,"ready"))rc=PROBE_NOT_READY;
    else if(op==PROBE_STREAM_WRITE){
        portENTER_CRITICAL(&status_mux);
        if(status.measure_start_us){
            if(!status.measure_tx_start_us)status.measure_tx_start_us=esp_timer_get_time();
            status.measure_tx_bytes+=n;
        }
        portEXIT_CRITICAL(&status_mux);
        if(cdc_acm_host_data_tx_blocking(cdc,in,n,1000)!=ESP_OK)
            rc=uncertain("Binary transmit outcome unknown; do not replay");
    }else if(op==PROBE_STREAM_READ){
        *written=xStreamBufferReceive(rx,out,cap,pdMS_TO_TICKS(20));
        if(failed())rc=uncertain("Binary receive overflow or disconnect; do not replay");
    }
    /* OPEN/CLOSE only transfer ownership of the existing buffers. The native
     * MKLink runtime controls Pika/MUX transitions; the relay injects no bytes. */
    xSemaphoreGive(access);return rc;
}
static bool handshake(void){
    /* Identity echo and version are probe-local; no SWD/target command is issued. */
    static const char *commands[]={"\n","print('__mklink_wireless_9ac2__')\n","cmd.get_version()\n"};
    /* reply lives in response; memmove permits the overlap used by handshake. */
    uint8_t *reply=(uint8_t *)response->data;
    for(unsigned i=0;i<3;i++){
        size_t written=0;
        probe_result_t result=exchange_locked((const uint8_t *)commands[i],strlen(commands[i]),reply,
                                               sizeof response->data-1,&written,2000);
        if(result!=PROBE_OK)return false;
        if(i==1&&!mklink_reply_has_line(response,"__mklink_wireless_9ac2__")){
            state("error","Probe identity token missing; no backend admitted");return false;
        }
    }
    char version[160];
    if(!mklink_reply_version(response,version,sizeof version)){
        state("error","Unrecognized complete version response; no backend admitted");return false;
    }
    portENTER_CRITICAL(&status_mux);snprintf(status.version,sizeof status.version,"%s",version);portEXIT_CRITICAL(&status_mux);
    return true;
}
esp_err_t v4_backend_start(void){
    access=xSemaphoreCreateMutex();events=xEventGroupCreate();
    /* CPU-side queue only; CDC DMA buffers and FreeRTOS control stay internal. */
    response=heap_caps_malloc(sizeof *response,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!response)return ESP_ERR_NO_MEM;
    rx_storage=heap_caps_malloc(RX_BYTES+1,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!rx_storage)return ESP_ERR_NO_MEM;
    rx=xStreamBufferCreateStatic(RX_BYTES,1,rx_storage,&rx_control);
    if(!access||!events||!rx)return ESP_ERR_NO_MEM;
    const cdc_acm_host_driver_config_t driver={.driver_task_stack_size=6144,.driver_task_priority=10,.xCoreID=0};
    return cdc_acm_host_install(&driver);
}
void v4_backend_attach(unsigned address,usb_device_handle_t device){
    const usb_device_desc_t *identity;const usb_config_desc_t *config;usb_device_info_t info;
    if(usb_host_get_device_descriptor(device,&identity)!=ESP_OK||identity->idVendor!=0x0d28||identity->idProduct!=0x0202)return;
    v4_backend_status_t current;v4_backend_snapshot(&current);if(current.address)return;
    if(usb_host_device_info(device,&info)!=ESP_OK||usb_host_get_active_config_descriptor(device,&config)!=ESP_OK)return;
    mklink_cdc_layout_t layout;
    if(info.speed!=USB_SPEED_FULL||!mklink_find_cdc((const uint8_t *)config,config->wTotalLength,4,&layout)){
        state("rejected","V4 command CDC layout or Full-Speed endpoints invalid");return;
    }
    probe_descriptor_t descriptor={.vid=identity->idVendor,.pid=identity->idProduct,.speed=1,
        .interface_number=layout.data_interface,.in_endpoint=layout.bulk_in,.out_endpoint=layout.bulk_out,
        .in_mps=layout.bulk_in_mps,.out_mps=layout.bulk_out_mps};
    if(!probe_descriptor_compatible(&descriptor)){state("rejected","USB Bulk packet size rejected");return;}
    portENTER_CRITICAL(&status_mux);status.address=address;status.in_mps=layout.bulk_in_mps;
    status.out_mps=layout.bulk_out_mps;status.version[0]=0;portEXIT_CRITICAL(&status_mux);
    state("opening",NULL);
    const cdc_acm_host_open_config_t open={.vid=0x0d28,.pid=0x0202,.interface_idx=4,.dev_addr=address,
        .connection_timeout_ms=1500,.out_buffer_size=1024,.in_buffer_size=4096,.event_cb=event,.data_cb=receive};
    xSemaphoreTake(access,portMAX_DELAY);xEventGroupClearBits(events,FAULTS);
    esp_err_t err=cdc_acm_host_open(&open,&cdc);
    bool ready=false;
    if(err==ESP_OK){
        const cdc_acm_line_coding_t coding={.dwDTERate=115200,.bDataBits=8};
        err=cdc_acm_host_line_coding_set(cdc,&coding);
        if(err==ESP_OK)err=cdc_acm_host_set_control_line_state(cdc,true,true);
        if(err==ESP_OK){state("handshake",NULL);vTaskDelay(pdMS_TO_TICKS(100));ready=handshake();}
        else state("error","CDC line/control setup failed");
    }else state("error","Unable to open V4 command interface");
    if(!ready&&cdc){cdc_acm_host_close(cdc);cdc=NULL;}
    xSemaphoreGive(access);
    /* Lock order is rpc_lock -> access. Never call bind/unbind while holding access. */
    const probe_backend_t backend={.exchange=exchange,.stream=stream};
    if(ready&&config_bind_probe(&descriptor,&backend)){
        state("ready",NULL);ESP_LOGI(TAG,"V4_HANDSHAKE_PASS address=%u mps=%u/%u target_commands=NONE",address,layout.bulk_in_mps,layout.bulk_out_mps);
    }else if(ready){state("error","Node executor rejected backend");}
}
void v4_backend_detach(unsigned address){
    v4_backend_status_t current;v4_backend_snapshot(&current);if(current.address!=address)return;
    xEventGroupSetBits(events,GONE);config_unbind_probe();
    xSemaphoreTake(access,portMAX_DELAY);
    if(cdc){esp_err_t err=cdc_acm_host_close(cdc);if(err!=ESP_OK)ESP_LOGW(TAG,"CDC close: %s",esp_err_to_name(err));cdc=NULL;}
    uint8_t chunk[256];while(xStreamBufferReceive(rx,chunk,sizeof chunk,0)){}
    portENTER_CRITICAL(&status_mux);memset(&status,0,sizeof status);strcpy(status.state,"not_connected");portEXIT_CRITICAL(&status_mux);
    xSemaphoreGive(access);
}
