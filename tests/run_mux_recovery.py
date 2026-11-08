"""Compile the real bounded backend recovery with transport fault doubles."""
from pathlib import Path
import subprocess,os
root=Path(__file__).resolve().parents[1];main=root/'boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main';out=root/'tmp/mux-recovery-test';out.mkdir(parents=True,exist_ok=True)
s=(main/'v4_backend.c').read_text();code=s[s.index('probe_result_t v4_backend_recover(void)'):s.index('esp_err_t v4_backend_start(void)')]
pre=r'''
#include "mux_recovery.h"
#include "probe_transport.h"
#include <assert.h>
#include <stdio.h>
#define pdTRUE 1
#define ESP_OK 0
#define pdMS_TO_TICKS(x) (x)
static int access,rx,cdc=1,mode,tx,checks,given;static bool mux_mode=true;static int64_t clock_us;static uint8_t last[20];
static int xSemaphoreTake(int a,int t){(void)a;(void)t;return mode==1?0:1;}
static void xSemaphoreGive(int a){(void)a;given++;}
static bool failed(void){return mode==2;}
static void state(const char *n,const char *e){(void)n;(void)e;}
static bool handshake(void){checks++;return mode==9||(checks>1&&mode!=8);}
static uint32_t esp_random(void){return 0x12345678;}
static int64_t esp_timer_get_time(void){return clock_us;}
static int cdc_acm_host_data_tx_blocking(int c,const uint8_t *p,size_t n,unsigned timeout){
 (void)c;assert(n==20&&timeout==1000);assert(p[5]==1||p[5]==3);memcpy(last,p,20);tx++;
 return mode==3||(mode==4&&tx==2)?-1:0;
}
static size_t xStreamBufferReceive(int r,uint8_t *p,size_t n,unsigned wait){
 (void)r;(void)wait;assert(n>=29);clock_us+=20000;
 if(mode==5)return 0;
 bool hello=last[5]==1;unsigned bytes=hello?29:21;memset(p,0,bytes);memcpy(p,last,16);p[5]|=0x80;p[6]=bytes-20;
 mux_put(p+8,mode==7&&!hello?88:77);if(hello)mux_put(p+17,3);
 if(mode==6)mux_put(p+12,0x87654321);
 mux_put(p+bytes-4,mux_crc(p,bytes-4));return bytes;
}
'''
post=r'''
int main(void){
 for(mode=0;mode<=9;mode++){
  tx=checks=given=0;clock_us=0;mux_mode=true;
  probe_result_t result=v4_backend_recover();
  if(!mode){assert(result==PROBE_OK&&tx==2&&checks==2&&!mux_mode);}
  else if(mode==9){assert(result==PROBE_OK&&tx==0&&checks==1&&!mux_mode);}
  else {assert(result!=PROBE_OK&&mux_mode);assert(tx<=2);}
  if(mode==3||mode==5||mode==6)assert(tx==1);
  assert(clock_us<=4000000);assert(given==(mode!=1));
 }
 mode=0;mux_mode=false;tx=0;assert(v4_backend_recover()!=PROBE_OK&&tx==0);
 puts("Backend MUX recovery: HELLO/EXIT, TX uncertainty, timeout, stale reply, wrong epoch, identity failure and unknown mode PASS");
}
'''
(out/'test.c').write_text(pre+code+post)
subprocess.run([os.environ.get('CC','gcc'),'-std=c11','-Wall','-Wextra','-Werror',f'-I{main}',str(out/'test.c'),'-o',str(out/'test.exe')],check=True)
subprocess.run([str(out/'test.exe')],check=True)
