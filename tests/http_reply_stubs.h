/* Host doubles for the sender's direct platform dependencies; no serial/HIL. */
#pragma once
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0600
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM 0x101
#define ESP_ERR_INVALID_STATE 0x103
#define MALLOC_CAP_SPIRAM 4
#define MALLOC_CAP_8BIT 2
#define SHUT_RDWR 2
#define pdTRUE 1
#define pdPASS 1
#define portMAX_DELAY UINT32_MAX
typedef SRWLOCK portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED SRWLOCK_INIT
#define portENTER_CRITICAL(p) AcquireSRWLockExclusive(p)
#define portEXIT_CRITICAL(p) ReleaseSRWLockExclusive(p)
typedef struct {int fd;} httpd_req_t;
typedef void *TaskHandle_t;
typedef struct {void *items[3];unsigned count;} *QueueHandle_t;
static bool fail_queue_create, fail_begin, fail_queue_send, fail_complete;
static int fail_task_at=-1, task_calls, task_deleted, queue_deleted;
static unsigned begin_calls, completes, shutdowns, send_calls;
static int last_shutdown=-1;
static uint32_t mock_ms=100;
static HANDLE slow_entered, slow_release;
static inline int64_t esp_timer_get_time(void){return (int64_t)mock_ms*1000;}
static inline unsigned uxTaskGetStackHighWaterMark(void *task){(void)task;return 2048;}
static inline int httpd_req_to_sockfd(httpd_req_t *r){return r->fd;}
static inline esp_err_t httpd_req_async_handler_begin(httpd_req_t *r,httpd_req_t **out){
    begin_calls++;
    if(fail_begin)return ESP_ERR_NO_MEM;
    *out=malloc(sizeof **out);assert(*out);**out=*r;return ESP_OK;
}
static inline esp_err_t httpd_req_async_handler_complete(httpd_req_t *r){
    if(r->fd==22 || r->fd==23 || r->fd==25)assert(last_shutdown==r->fd);
    completes++;free(r);return fail_complete?ESP_FAIL:ESP_OK;
}
static inline int shutdown(int fd,int how){assert(how==SHUT_RDWR);last_shutdown=fd;shutdowns++;return 0;}
static inline esp_err_t httpd_resp_send(httpd_req_t *r,const char *p,ptrdiff_t n){
    assert(p && n==4 && !memcmp(p,"data",4));
    if(r->fd==20){SetEvent(slow_entered);assert(WaitForSingleObject(slow_release,5000)==WAIT_OBJECT_0);}
    InterlockedIncrement((volatile LONG *)&send_calls);
    return r->fd==22?ESP_FAIL:ESP_OK;
}
static inline QueueHandle_t xQueueCreate(unsigned n,size_t item){
    assert(n==3 && item==sizeof(void*));
    return fail_queue_create?NULL:calloc(1,sizeof(struct {void *items[3];unsigned count;}));
}
static inline void vQueueDelete(QueueHandle_t q){queue_deleted++;free(q);}
static inline int xQueueSend(QueueHandle_t q,void *item,unsigned ticks){
    assert(ticks==0);
    if(fail_queue_send || q->count==3)return 0;
    q->items[q->count++]=*(void**)item;return 1;
}
static inline int xQueueReceive(QueueHandle_t q,void *out,unsigned ticks){
    (void)ticks;if(!q->count)return 0;
    *(void**)out=q->items[0];q->count--;memmove(q->items,q->items+1,q->count*sizeof(void*));return 1;
}
static inline int xTaskCreateWithCaps(void(*f)(void*),const char*n,unsigned stack,void*a,unsigned priority,TaskHandle_t*h,unsigned caps){
    (void)f;(void)n;(void)a;assert(stack==4096 && priority==5 && caps==(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(task_calls++==fail_task_at)return 0;
    *h=(void*)(uintptr_t)task_calls;return 1;
}
static inline void vTaskDeleteWithCaps(TaskHandle_t task){assert(task);task_deleted++;}
