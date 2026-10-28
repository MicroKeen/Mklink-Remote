#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "node_policy.h"
static const char *a="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",*b="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
int main(void){
    button_state_t key={0};
    assert(button_update(&key,true,0)==BUTTON_NONE); /* Holding at boot cannot change mode. */
    assert(button_update(&key,true,5000)==BUTTON_NONE);
    assert(button_update(&key,false,5100)==BUTTON_NONE);
    button_update(&key,true,5200);button_update(&key,false,5300);button_update(&key,true,5400);
    assert(button_update(&key,false,5500)==BUTTON_TOGGLE);
    button_update(&key,true,6000);assert(button_update(&key,true,9100)==BUTTON_NONE);
    assert(button_update(&key,false,9200)==BUTTON_RECOVER_AP);
    assert(!key.long_seen);
    assert(button_update(&key,false,9300)==BUTTON_NONE);
    button_update(&key,true,9400);button_update(&key,false,9410);button_update(&key,true,9420);
    assert(button_update(&key,false,9430)==BUTTON_NONE); /* Contact bounce cannot double-click. */
    control_lease_t lease={0};
    assert(lease_acquire(&lease,"terminal-A",a,100));
    assert(!lease_acquire(&lease,"terminal-B",b,200));
    assert(!lease_authorized(&lease,b,300));
    assert(!lease_release(&lease,b,300));
    assert(lease_authorized(&lease,a,300));
    lease.busy=true;
    assert(!lease_release(&lease,a,400));
    assert(!lease_acquire(&lease,"terminal-B",b,20000)); /* Expired in-flight ownership stays quarantined. */
    assert(!lease_authorized(&lease,a,20000));
    lease.busy=false;
    assert(lease_acquire(&lease,"terminal-B",b,20000));
    assert(lease_release(&lease,b,20100));
    assert(!lease.owner[0]);
    assert(center_url_valid("wss://hil.example:443"));
    assert(center_url_valid("ws://192.168.50.1:8910"));
    assert(!center_url_valid("ws://192.168.50.1.evil.example"));
    assert(!center_url_valid("ws://10.0.0.1:8910@evil.example"));
    assert(!center_url_valid("ws://8.8.8.8:8910"));
    assert(!center_url_valid("ws://010.0.0.1:8910"));
    assert(!center_url_valid("ws://10.0.0.1:70000"));
    assert(!center_url_valid("wss://user:token@hil.example"));
    puts("PASS: BOOT gestures and exclusive control lease failure paths");
    return 0;
}
