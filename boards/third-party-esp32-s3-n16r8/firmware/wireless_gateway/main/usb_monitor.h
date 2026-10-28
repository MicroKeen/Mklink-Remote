#pragma once
#include <stdbool.h>
typedef struct { bool connected; unsigned vid,pid,speed,invalid_bulk,interfaces,endpoints; } usb_monitor_status_t;
void usb_monitor_snapshot(usb_monitor_status_t *out);
void usb_monitor_task(void *arg);
