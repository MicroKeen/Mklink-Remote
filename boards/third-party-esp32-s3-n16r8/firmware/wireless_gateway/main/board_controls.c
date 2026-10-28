/* Board SCH: BOOT -> GPIO0/GND; U1 WS2812B DI -> GPIO48 through 0 ohm.
 * RMT symbols follow IDF v5.5.2 WS2812 example; low brightness, one GRB pixel. */
#include "board_controls.h"
#include "center_client.h"
#include "driver/gpio.h"
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "network_manager.h"
#include "node_policy.h"
#include <string.h>
static uint64_t hint_until;
static portMUX_TYPE hint_mux = portMUX_INITIALIZER_UNLOCKED;
void board_controls_hint(void) {
    portENTER_CRITICAL(&hint_mux);
    hint_until = esp_timer_get_time() / 1000 + 900;
    portEXIT_CRITICAL(&hint_mux);
}
static rmt_channel_handle_t tx;
static rmt_encoder_handle_t encoder;
static void pixel(unsigned red, unsigned green, unsigned blue) {
    unsigned grb = (green << 16) | (red << 8) | blue;
    rmt_symbol_word_t symbols[25] = {0};
    for (unsigned i = 0; i < 24; i++) {
        bool one = grb & (1u << (23 - i));
        symbols[i].level0 = 1;
        symbols[i].duration0 = one ? 9 : 4;
        symbols[i].level1 = 0;
        symbols[i].duration1 = one ? 4 : 9;
    }
    symbols[24].duration0 = 500;
    symbols[24].duration1 = 500;
    rmt_transmit_config_t config = {.loop_count = 0};
    if (rmt_transmit(tx, encoder, symbols, sizeof(symbols), &config) == ESP_OK)
        rmt_tx_wait_all_done(tx, 30);
}
static void task(void *arg) {
    (void)arg;
    button_state_t button = {0};
    bool last = false, stable = false;
    unsigned count = 0, frame = 0;
    for (;;) {
        bool down = gpio_get_level(GPIO_NUM_0) == 0;
        if (down == last) {
            if (count < 3)
                count++;
        } else {
            last = down;
            count = 0;
        }
        if (count >= 2)
            stable = down;
        uint64_t now = esp_timer_get_time() / 1000;
        button_action_t action = button_update(&button, stable, now);
        if (action != BUTTON_NONE)
            config_button_action(action);
        if (frame++ % 5 == 0) {
            network_status_t n;
            network_snapshot(&n);
            center_status_t c;
            center_snapshot(&c);
            bool ready = !strcmp(n.actual, "AP") ? n.ap_clients > 0 : !strcmp(n.sta_state, "connected");
            bool on = ready || (now / 600) % 2 == 0;
            unsigned r = 0, g = 0, b = 0;
            if (!strcmp(n.actual, "AP")) {
                b = on ? 16 : 0;
            } else if (!strcmp(n.actual, "STA")) {
                g = on ? 16 : 0;
            } else {
                r = on ? 10 : 0;
                b = on ? 16 : 0;
            }
            portENTER_CRITICAL(&hint_mux);
            uint64_t hint = hint_until;
            portEXIT_CRITICAL(&hint_mux);
            if (n.switching || now < hint || button.long_seen) {
                r = 16;
                g = 8;
                b = 0;
            } else if (n.error[0] && !n.ap_active) {
                r = (now / 180) % 2 ? 18 : 0;
                g = 0;
                b = 0;
            }
            if (c.control_online && now % 4000 < 100)
                r = g = b = 12;
            pixel(r, g, b);
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
esp_err_t board_controls_start(void) {
    gpio_config_t key = {
        .pin_bit_mask = 1ULL << GPIO_NUM_0, .mode = GPIO_MODE_INPUT, .pull_up_en = GPIO_PULLUP_ENABLE};
    esp_err_t err = gpio_config(&key);
    if (err != ESP_OK)
        return err;
    rmt_tx_channel_config_t config = {.gpio_num = GPIO_NUM_48,
                                      .clk_src = RMT_CLK_SRC_DEFAULT,
                                      .resolution_hz = 10000000,
                                      .mem_block_symbols = 64,
                                      .trans_queue_depth = 2};
    if ((err = rmt_new_tx_channel(&config, &tx)) != ESP_OK)
        return err;
    rmt_copy_encoder_config_t copy = {};
    if ((err = rmt_new_copy_encoder(&copy, &encoder)) != ESP_OK)
        return err;
    if ((err = rmt_enable(tx)) != ESP_OK)
        return err;
    return xTaskCreate(task, "board_controls", 4096, NULL, 2, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
