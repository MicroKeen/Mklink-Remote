#include "node_policy.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
button_action_t button_update(button_state_t *s, bool down, uint64_t now) {
    if (!s->armed) {
        if (!down)
            s->armed = true;
        return BUTTON_NONE;
    }
    if (down != s->pressed) {
        if (down) {
            s->pressed = true;
            s->changed_ms = now;
            s->long_seen = false;
        } else {
            s->pressed = false;
            s->long_seen = false;
            uint64_t held = now - s->changed_ms;
            if (held >= 3000) {
                s->pending_click = false;
                return BUTTON_RECOVER_AP;
            }
            if (held >= 40) {
                if (s->pending_click && now - s->click_ms <= 400) {
                    s->pending_click = false;
                    return BUTTON_TOGGLE;
                }
                s->pending_click = true;
                s->click_ms = now;
            }
        }
    }
    if (down && now - s->changed_ms >= 3000) {
        s->long_seen = true;
        s->pending_click = false;
    }
    if (s->pending_click && now - s->click_ms > 400)
        s->pending_click = false;
    return BUTTON_NONE;
}
void lease_expire(control_lease_t *s, uint64_t now) {
    if (s->owner[0] && now >= s->expires_ms && !s->busy)
        memset(s, 0, sizeof(*s));
}
bool lease_authorized(control_lease_t *s, const char *token, uint64_t now) {
    lease_expire(s, now);
    if (!token || strlen(token) != 32 || !s->owner[0] || now >= s->expires_ms)
        return false;
    unsigned diff = 0;
    for (unsigned i = 0; i < 32; i++)
        diff |= (unsigned char)token[i] ^ (unsigned char)s->token[i];
    return diff == 0;
}
bool lease_acquire(control_lease_t *s, const char *owner, const char *token, uint64_t now) {
    lease_expire(s, now);
    if (s->owner[0] || !owner || !owner[0] || strlen(owner) >= 64 || !token || strlen(token) != 32)
        return false;
    strcpy(s->owner, owner);
    strcpy(s->token, token);
    s->expires_ms = now + 15000;
    return true;
}
bool lease_release(control_lease_t *s, const char *token, uint64_t now) {
    if (!lease_authorized(s, token, now) || s->busy)
        return false;
    memset(s, 0, sizeof(*s));
    return true;
}
bool center_url_valid(const char *url) {
    if (!url || !url[0])
        return true;
    const char *host = !strncmp(url, "wss://", 6) ? url + 6 : !strncmp(url, "ws://", 5) ? url + 5 : NULL;
    if (!host || !host[0] || strpbrk(host, "/@?# \t\r\n"))
        return false;
    if (!strncmp(url, "ws://", 5)) {
        unsigned a, b, c, d;
        int used = 0;
        if (sscanf(host, "%u.%u.%u.%u%n", &a, &b, &c, &d, &used) != 4 || a > 255 || b > 255 || c > 255 ||
            d > 255)
            return false;
        char canonical[20];
        snprintf(canonical, sizeof(canonical), "%u.%u.%u.%u", a, b, c, d);
        if ((int)strlen(canonical) != used || strncmp(host, canonical, used))
            return false;
        if (host[used]) {
            if (host[used++] != ':' || !host[used])
                return false;
            for (const char *p = host + used; *p; p++)
                if (!isdigit((unsigned char)*p))
                    return false;
            unsigned long port = strtoul(host + used, NULL, 10);
            if (!port || port > 65535)
                return false;
        }
        if (!(a == 10 || a == 127 || (a == 192 && b == 168) || (a == 172 && b >= 16 && b <= 31)))
            return false;
    }
    return true;
}
