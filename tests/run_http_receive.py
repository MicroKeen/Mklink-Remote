"""Exercise the actual RPC receive/execute callbacks with bounded host IO."""
from pathlib import Path
import subprocess,os
root=Path(__file__).resolve().parents[1];out=root/'tmp/http-receive-test';out.mkdir(parents=True,exist_ok=True)
s=(root/'boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main/config_rpc.c').read_text()
code=s[s.index('typedef struct { http_reply_t *pending;'):s.index('static esp_err_t http_rpc(')]
pre=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_NO_MEM -2
#define HTTPD_SOCK_ERR_TIMEOUT -3
#define HTTP_DIAG_ALLOC_ERROR 1
#define HTTP_DIAG_PROCESSED 2
#define HTTP_DIAG_BEGIN 3
#define HTTP_DIAG_RECV_ERROR 4
#define HTTP_DIAG_BODY 5
#define RPC_HTTP 1
#include <stdbool.h>
typedef struct {int content_len;void *handle;} httpd_req_t;
typedef struct {httpd_req_t req;} http_reply_t;
static unsigned clock_ms,aborts,sends,executed,offset,step;
static int mode;static const char *input;static void (*queued)(void*);static void *queued_arg;
static httpd_req_t *http_reply_request(http_reply_t *r){return &r->req;}
static uint32_t http_reply_started(http_reply_t *r){(void)r;return 0;}
static uint32_t now_ms(void){return clock_ms;}
static void http_step(int s,int e,unsigned t){(void)s;(void)e;(void)t;}
static void http_reply_abort(http_reply_t *r){(void)r;aborts++;}
static void http_rpc_sent(uint32_t t,esp_err_t e){(void)t;(void)e;}
static char *process(const char *body,int transport){assert(transport==RPC_HTTP);assert(!strcmp(body,"{}"));executed++;char *p=malloc(3);memcpy(p,"{}",3);return p;}
static void httpd_resp_set_type(httpd_req_t *r,const char *v){(void)r;(void)v;}
static void httpd_resp_set_hdr(httpd_req_t *r,const char *k,const char *v){(void)r;(void)k;(void)v;}
static void httpd_resp_set_status(httpd_req_t *r,const char *v){(void)r;assert(!strcmp(v,"400 Bad Request"));}
static void http_reply_send(http_reply_t *r,const char *p,size_t n,bool owned,void(*done)(uint32_t,esp_err_t)){(void)r;(void)n;(void)done;sends++;if(owned)free((void*)p);}
static int httpd_req_recv(httpd_req_t *r,char *p,size_t n){(void)r;clock_ms+=step;if(mode==1)return -3;assert(n);*p=input[offset++];return 1;}
static int httpd_queue_work(void *h,void(*f)(void*),void *a){(void)h;if(mode==2)return -1;queued=f;queued_arg=a;return 0;}
'''
post=r'''
int main(void){
 http_reply_t r={{2,NULL}};input="{}";
 http_rpc_receive(&r);assert(queued&&executed==0&&aborts==0);queued(queued_arg);assert(executed==1&&sends==1);
 mode=1;offset=0;queued=NULL;http_rpc_receive(&r);assert(aborts==1&&!queued&&executed==1);
 mode=2;offset=0;http_rpc_receive(&r);assert(aborts==2&&!queued&&executed==1);
 mode=0;offset=0;input="x\0";http_rpc_receive(&r);assert(sends==2&&!queued&&executed==1);
 input="{}";offset=0;step=2100;clock_ms=0;http_rpc_receive(&r);assert(aborts==3&&!queued&&executed==1);
 puts("HTTP receive: defer execution, timeout, slow drip, embedded NUL and queue rejection PASS");
}
'''
(out/'test.c').write_text(pre+code+post)
subprocess.run([os.environ.get('CC','gcc'),'-std=c11','-Wall','-Wextra','-Werror',str(out/'test.c'),'-o',str(out/'test.exe')],check=True)
subprocess.run([str(out/'test.exe')],check=True)
