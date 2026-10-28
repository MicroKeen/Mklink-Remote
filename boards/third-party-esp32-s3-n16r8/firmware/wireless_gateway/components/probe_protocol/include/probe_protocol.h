#ifndef PROBE_PROTOCOL_H
#define PROBE_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint8_t control_interface;
    uint8_t data_interface;
    uint8_t bulk_in;
    uint8_t bulk_out;
    uint8_t interrupt_in;
    uint16_t bulk_in_mps;
    uint16_t bulk_out_mps;
} mklink_cdc_layout_t;

typedef struct {
    char data[4096];
    size_t length;
    /* Sticky invalid-input flag: overflow or an embedded NUL poisons the reply. */
    bool overflow;
} mklink_reply_t;

/* Failure leaves *out unchanged. Only alternate setting zero is selected.
 * The union slave must be control_interface + 1, matching the interface chosen
 * by pinned usb_host_cdc_acm 2.4.1. Control interface 255 is therefore invalid.
 * The data interface must contain exactly two bulk endpoints. */
bool mklink_find_cdc(const uint8_t *bytes, size_t length,
                     uint8_t control_interface, mklink_cdc_layout_t *out);
void mklink_reply_reset(mklink_reply_t *reply);
bool mklink_reply_feed(mklink_reply_t *reply, const uint8_t *bytes, size_t length);
bool mklink_reply_prompt(const mklink_reply_t *reply);
/* A line must be complete (newline terminated), and is whitespace trimmed. */
bool mklink_reply_has_line(const mklink_reply_t *reply, const char *line);
/* Returns the trimmed version output line, retaining its label if present.
 * Requires a completed prompt and rejects error replies. Failure is atomic. */
bool mklink_reply_version(const mklink_reply_t *reply, char *out, size_t capacity);

#endif
