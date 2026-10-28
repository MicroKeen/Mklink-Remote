#include "probe_protocol.h"

#include <string.h>

static uint16_t le16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

bool mklink_find_cdc(const uint8_t *bytes, size_t length,
                     uint8_t control_interface, mklink_cdc_layout_t *out)
{
    mklink_cdc_layout_t result = {0};
    bool seen[256] = {false};
    bool have_control = false, have_union = false, have_data = false;
    size_t offset, total;
    unsigned pass, interface_count = 0;
    if (bytes == NULL || out == NULL || control_interface == UINT8_MAX ||
        length < 9 || bytes[0] != 9 || bytes[1] != 2) {
        return false;
    }
    total = le16(bytes + 2);
    if (total < 9 || total > length) {
        return false;
    }
    result.control_interface = control_interface;
    /* First validate every descriptor and discover the union; then collect the
     * slave's endpoints. This also permits the data interface before control. */
    for (pass = 0; pass < 2; ++pass) {
        bool in_interface = false, alternate_zero = false;
        bool selected_control = false, selected_data = false;
        unsigned expected = 0, actual = 0;
        uint32_t endpoint_mask = 0;
        uint32_t active_endpoints = 0;
        for (offset = 9; offset < total; offset += bytes[offset]) {
            const uint8_t *d = bytes + offset;
            uint8_t size, type;
            if (total - offset < 2) { return false; }
            size = d[0]; type = d[1];
            if (size < 2 || size > total - offset) { return false; }
            if (type == 2) { return false; }
            if (type == 11 && size < 8) { return false; }
            if (type == 4) {
                if (size < 9 || (in_interface && actual != expected)) { return false; }
                in_interface = true;
                alternate_zero = d[3] == 0;
                actual = 0; expected = d[4]; endpoint_mask = 0;
                selected_control = d[2] == control_interface && d[3] == 0;
                selected_data = pass == 1 && d[2] == result.data_interface && d[3] == 0;
                if (pass == 0 && d[3] == 0) {
                    if (seen[d[2]]) { return false; }
                    seen[d[2]] = true; ++interface_count;
                }
                if (selected_control) {
                    if (d[5] != 2 || d[6] != 2) { return false; }
                    have_control = true;
                }
                if (selected_data) {
                    if (d[5] != 0x0a || d[4] != 2) { return false; }
                    have_data = true;
                }
            } else if (type == 5) {
                uint8_t address, transfer;
                uint16_t mps;
                uint32_t bit;
                if (!in_interface || size < 7) { return false; }
                address = d[2]; transfer = d[3] & 3u; mps = le16(d + 4);
                if ((address & 0x70u) != 0 || (address & 15u) == 0 || mps == 0 ||
                    (mps & 0xf800u) != 0 || ((transfer == 2 || transfer == 3) && mps > 64)) {
                    return false;
                }
                bit = (uint32_t)1u << ((address & 15u) + ((address & 0x80u) ? 16u : 0u));
                if ((endpoint_mask & bit) != 0) { return false; }
                endpoint_mask |= bit;
                if (alternate_zero) {
                    if ((active_endpoints & bit) != 0) { return false; }
                    active_endpoints |= bit;
                }
                ++actual;
                if (selected_control && pass == 0) {
                    if (transfer != 3 || !(address & 0x80u) || result.interrupt_in != 0) { return false; }
                    result.interrupt_in = address;
                }
                if (selected_data) {
                    if (transfer != 2) { return false; }
                    if (address & 0x80u) {
                        if (result.bulk_in != 0) { return false; }
                        result.bulk_in = address; result.bulk_in_mps = mps;
                    } else {
                        if (result.bulk_out != 0) { return false; }
                        result.bulk_out = address; result.bulk_out_mps = mps;
                    }
                }
            } else if (type == 0x24) {
                if (!in_interface || size < 3) { return false; }
                if (selected_control &&
                    (((d[2] == 0 || d[2] == 1) && size < 5) || (d[2] == 2 && size < 4))) {
                    return false;
                }
                if (selected_control && d[2] == 6 && pass == 0) {
                    if (size != 5 || have_union || d[3] != control_interface ||
                        d[4] != (uint8_t)(control_interface + 1u)) {
                        return false;
                    }
                    result.data_interface = d[4]; have_union = true;
                }
            }
        }
        if (in_interface && actual != expected) { return false; }
        if (pass == 0 && (!have_control || !have_union || interface_count != bytes[4])) { return false; }
    }
    if (!have_data || result.bulk_in == 0 || result.bulk_out == 0) { return false; }
    *out = result;
    return true;
}

void mklink_reply_reset(mklink_reply_t *reply)
{
    if (reply != NULL) {
        reply->length = 0; reply->overflow = false; reply->data[0] = '\0';
    }
}

static bool valid_reply(const mklink_reply_t *reply)
{
    return reply != NULL && !reply->overflow && reply->length < sizeof reply->data &&
        reply->data[reply->length] == '\0';
}

bool mklink_reply_feed(mklink_reply_t *reply, const uint8_t *bytes, size_t length)
{
    if (!valid_reply(reply)) { return false; }
    if ((bytes == NULL && length != 0) || length > sizeof reply->data - 1 - reply->length ||
        (length != 0 && memchr(bytes, 0, length) != NULL)) {
        reply->overflow = true;
        return false;
    }
    if (length != 0) { memcpy(reply->data + reply->length, bytes, length); }
    reply->length += length;
    reply->data[reply->length] = '\0';
    return true;
}

static bool whitespace(char c)
{
    return c == ' ' || c == '\t' || c == '\r';
}

bool mklink_reply_prompt(const mklink_reply_t *reply)
{
    size_t end, start;
    if (!valid_reply(reply)) { return false; }
    end = reply->length;
    while (end != 0 && (whitespace(reply->data[end - 1]) || reply->data[end - 1] == '\n')) { --end; }
    start = end;
    while (start != 0 && reply->data[start - 1] != '\n' && reply->data[start - 1] != '\r') { --start; }
    while (start < end && whitespace(reply->data[start])) { ++start; }
    return end - start == 3 && memcmp(reply->data + start, ">>>", 3) == 0;
}

/* Returns each complete line as a trimmed byte range. */
static bool next_line(const mklink_reply_t *reply, size_t *position, size_t *start, size_t *end)
{
    size_t i = *position;
    *start = i;
    while (i < reply->length && reply->data[i] != '\n' && reply->data[i] != '\r') { ++i; }
    if (i == reply->length) { return false; }
    *end = i;
    *position = i + 1;
    while (*start < *end && whitespace(reply->data[*start])) { ++*start; }
    while (*end > *start && whitespace(reply->data[*end - 1])) { --*end; }
    return true;
}

bool mklink_reply_has_line(const mklink_reply_t *reply, const char *line)
{
    size_t position = 0, start, end, length;
    if (!valid_reply(reply) || line == NULL || *line == '\0') { return false; }
    length = strlen(line);
    while (next_line(reply, &position, &start, &end)) {
        if (end - start == length && memcmp(reply->data + start, line, length) == 0) { return true; }
    }
    return false;
}

static bool version_line(const char *line, size_t length)
{
    size_t i = 0;
    unsigned parts = 0;
    if (length >= 10 && memcmp(line, "MicroKeen ", 10) == 0) { i = 10; }
    else if (length >= 8 && memcmp(line, "VERSION=", 8) == 0) { i = 8; }
    if (i < length && line[i] == 'V') { ++i; }
    while (i < length) {
        size_t begin = i;
        while (i < length && line[i] >= '0' && line[i] <= '9') { ++i; }
        if (i == begin) { return false; }
        ++parts;
        if (i == length) { return parts == 3; }
        if (line[i++] != '.' || parts >= 3) { return false; }
    }
    return false;
}

bool mklink_reply_version(const mklink_reply_t *reply, char *out, size_t capacity)
{
    size_t position = 0, start, end, match_start = 0, match_length = 0;
    if (!mklink_reply_prompt(reply) || out == NULL || capacity == 0) { return false; }
    if (strstr(reply->data, "Traceback") != NULL || strstr(reply->data, "Error") != NULL) { return false; }
    while (next_line(reply, &position, &start, &end)) {
        if (match_length == 0 && version_line(reply->data + start, end - start)) {
            match_start = start; match_length = end - start;
        }
    }
    if (match_length == 0 || match_length >= capacity) { return false; }
    memcpy(out, reply->data + match_start, match_length);
    out[match_length] = '\0';
    return true;
}
