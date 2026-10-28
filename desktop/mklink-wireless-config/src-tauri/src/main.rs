#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
fn main() {
    mklink_remote_core::run();
}
