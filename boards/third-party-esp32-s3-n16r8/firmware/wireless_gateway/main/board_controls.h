#pragma once
#include "esp_err.h"
esp_err_t board_controls_start(void);
void config_button_action(int action);
void board_controls_hint(void);
