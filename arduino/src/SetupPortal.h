#pragma once

// Runs the first-boot setup portal: open AP "K7-Setup", captive DNS,
// HTML form to scan/select/save the lamp SSID.  Saves /config.json and
// restarts the device.  Does not return on success.
void runSetupPortal();
