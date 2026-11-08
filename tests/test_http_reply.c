#include "http_reply_stubs.h"
#include <stdio.h>
static void *tracked_payload;
static unsigned payload_frees, callbacks;
static esp_err_t callback_error;
static void tracked_free(void *p){if(p && p==tracked_payload){payload_frees++;tracked_payload=NULL;}free(p);}
#define free tracked_free
#include "../boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main/http_reply.c"
#undef free

static void done(uint32_t started,esp_err_t err){assert(started==100);callbacks++;callback_error=err;}
static char *payload(void){char *p=malloc(5);memcpy(p,"data",5);assert(!tracked_payload);tracked_payload=p;return p;}
static http_reply_t *begin(int fd){httpd_req_t req={.fd=fd};return http_reply_begin(&req);}
static http_reply_t *pop(void){http_reply_t *r=NULL;assert(xQueueReceive(queue,&r,0));return r;}
static unsigned received;
static void receive_body(http_reply_t *r){received++;assert(http_reply_send(r,"data",4,false,NULL)==ESP_OK);}
static DWORD WINAPI slow_sender(void *arg){send_reply(arg);return 0;}

int main(void){
    assert(!begin(1));
    fail_queue_create=true;assert(http_reply_init()==ESP_ERR_NO_MEM);fail_queue_create=false;
    fail_task_at=1;assert(http_reply_init()==ESP_ERR_NO_MEM);
    assert(!queue && task_deleted==1 && queue_deleted==1);
    fail_task_at=-1;assert(http_reply_init()==ESP_OK);
    assert(http_reply_init()==ESP_ERR_INVALID_STATE);
    fail_begin=true;assert(!begin(1));assert(status.active==0);fail_begin=false;

    http_reply_t *a=begin(10),*b=begin(11),*c=begin(12);
    assert(a && b && c && status.active==3);
    unsigned clones=begin_calls;
    assert(!begin(13) && begin_calls==clones); /* Reject before creating/executing a request. */
    http_reply_abort(a);http_reply_abort(b);http_reply_abort(c);assert(status.active==0);

    a=begin(25);fail_queue_send=true;
    assert(http_reply_send(a,payload(),4,true,done)==ESP_FAIL);
    fail_queue_send=false;assert(status.active==0 && payload_frees==1 && callbacks==1 && callback_error==ESP_FAIL);

    slow_entered=CreateEvent(NULL,TRUE,FALSE,NULL);slow_release=CreateEvent(NULL,TRUE,FALSE,NULL);
    assert(slow_entered && slow_release);
    a=begin(20);b=begin(21);
    assert(http_reply_send(a,"data",4,false,NULL)==ESP_OK);
    assert(http_reply_send(b,"data",4,false,done)==ESP_OK);
    HANDLE thread=CreateThread(NULL,0,slow_sender,pop(),0,NULL);assert(thread);
    assert(WaitForSingleObject(slow_entered,5000)==WAIT_OBJECT_0);
    send_reply(pop());
    http_reply_status_t observed;http_reply_snapshot(&observed);
    assert(observed.active==1 && observed.slots[a-replies].stage==HTTP_REPLY_SENDING);
    assert(callbacks==2 && callback_error==ESP_OK); /* Fast reply completed while slow one is blocked. */
    SetEvent(slow_release);assert(WaitForSingleObject(thread,5000)==WAIT_OBJECT_0);
    CloseHandle(thread);CloseHandle(slow_entered);CloseHandle(slow_release);
    assert(status.active==0);

    a=begin(22);assert(http_reply_send(a,payload(),4,true,done)==ESP_OK);send_reply(pop());
    assert(payload_frees==2 && status.send_errors==1 && status.active==0 && callback_error==ESP_FAIL);
    a=begin(23);http_reply_abort(a);assert(status.active==0);
    a=begin(24);fail_complete=true;
    assert(http_reply_send(a,"data",4,false,NULL)==ESP_OK);send_reply(pop());fail_complete=false;
    assert(status.completion_errors==1 && status.active==0);

    a=begin(31);assert(http_reply_receive(a,receive_body)==ESP_OK);
    http_reply_t *pending=pop();assert(received==0 && pending==a);
    void (*receive_fn)(http_reply_t *)=pending->receive;pending->receive=NULL;
    receive_fn(pending);assert(received==1);send_reply(pop());assert(status.active==0);
    a=begin(32);fail_queue_send=true;assert(http_reply_receive(a,receive_body)==ESP_FAIL);
    fail_queue_send=false;assert(received==1 && status.active==0);
    for(unsigned i=0;i<1000;i++){
        a=begin(30);assert(a);
        assert(http_reply_send(a,payload(),4,true,NULL)==ESP_OK);send_reply(pop());
        assert(status.active==0 && !tracked_payload);
    }
    assert(payload_frees==1002 && queue->count==0 && status.stack_min_bytes==2048);
    assert(completes==status.accepted);
    puts("http_reply: bounded admission, concurrent slow/fast send, failures, ownership and 1000 reuse cycles PASS");
    return 0;
}
