#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum { CHECK_LOW_SPEED, CHECK_FULL_SPEED, CHECK_HIGH_SPEED } check_speed_t;
typedef struct {
    unsigned interfaces;
    unsigned endpoints;
    unsigned invalid_bulk;
    bool command_control_if4;
    bool command_data_if5;
    bool command_out07;
    bool command_in87;
} descriptor_summary_t;

/* Visitor receives only descriptors whose minimum size and bounds were checked.
 * Return value covers structure/bounds only; bulk legality is in invalid_bulk.
 * Does not claim complete USB descriptor or CDC functional conformance.
 */
typedef void (*descriptor_visitor_t)(const uint8_t *desc, int interface_number,
                                     int alternate, bool bulk_valid, void *arg);
bool descriptor_check(const uint8_t *data, size_t size, check_speed_t speed,
                      descriptor_summary_t *summary,
                      descriptor_visitor_t visitor, void *arg);
