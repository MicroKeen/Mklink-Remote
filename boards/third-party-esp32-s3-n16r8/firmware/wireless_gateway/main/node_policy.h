#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef enum { BUTTON_NONE, BUTTON_TOGGLE, BUTTON_RECOVER_AP } button_action_t;
typedef struct { bool pressed, armed, long_seen, pending_click; uint64_t changed_ms, click_ms; } button_state_t;
button_action_t button_update(button_state_t *s, bool down, uint64_t now);
typedef struct { char owner[64], token[33]; uint64_t expires_ms; bool busy; } control_lease_t;
void lease_expire(control_lease_t *s, uint64_t now);
bool lease_authorized(control_lease_t *s, const char *token, uint64_t now);
bool lease_acquire(control_lease_t *s, const char *owner, const char *token, uint64_t now);
bool lease_release(control_lease_t *s, const char *token, uint64_t now);
bool center_url_valid(const char *url);
