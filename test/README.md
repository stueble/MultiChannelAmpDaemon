# Overview
Test scripts to to used with the MultiChannelAmpDaemon.

## usb_alsa_test.py

This script will test suspend/resume for configured devices. Make sure you have configured the correct ALSA card numbers and USB device paths in the TEST_DEVICES list. Run with '--detect' to find your devices first.
    
Needed for future extensions of the daemon that will suspend USB sound cards not in use.
