#include "descriptor_check.h"
#include <string.h>

static uint16_t read_le16(const uint8_t *p)
{
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static bool valid_bulk(uint16_t raw_mps, check_speed_t speed)
{
    /* USB 2.0 section 5.8.3: FS Bulk MPS = 8/16/32/64, HS = 512;
     * Low Speed has no Bulk transfers. Reserved/high-bandwidth bits are zero.
     */
    if (speed == CHECK_FULL_SPEED) {
        return raw_mps == 8 || raw_mps == 16 || raw_mps == 32 || raw_mps == 64;
    }
    return speed == CHECK_HIGH_SPEED && raw_mps == 512;
}

bool descriptor_check(const uint8_t *data, size_t size, check_speed_t speed,
                      descriptor_summary_t *summary,
                      descriptor_visitor_t visitor, void *arg)
{
    if (!summary) return false;
    memset(summary, 0, sizeof(*summary));
    if (!data || size < 9 || data[0] < 9 || data[1] != 2) return false;
    const size_t total = read_le16(data + 2);
    if (total < 9 || total > size) return false;
    int iface = -1;
    int alternate = -1;
    bool command_data = false;
    for (size_t offset = 0; offset < total;) {
        if (total - offset < 2) return false;
        const uint8_t *desc = data + offset;
        const size_t length = desc[0];
        if (length < 2 || length > total - offset) return false;
        bool bulk_valid = true;
        if (desc[1] == 4) {
            if (length < 9) return false;
            iface = desc[2];
            alternate = desc[3];
            command_data = iface == 5 && alternate == 0 && desc[5] == 0x0a;
            summary->interfaces++;
            if (iface == 4 && alternate == 0 && desc[5] == 2 && desc[6] == 2) {
                summary->command_control_if4 = true;
            }
            if (command_data) summary->command_data_if5 = true;
        } else if (desc[1] == 5) {
            if (length < 7 || iface < 0) return false;
            summary->endpoints++;
            if ((desc[3] & 3) == 2) {
                bulk_valid = valid_bulk(read_le16(desc + 4), speed);
                if (!bulk_valid) summary->invalid_bulk++;
                if (command_data && desc[2] == 0x07) summary->command_out07 = true;
                if (command_data && desc[2] == 0x87) summary->command_in87 = true;
            }
        }
        if (visitor) visitor(desc, iface, alternate, bulk_valid, arg);
        offset += length;
    }
    return true;
}
