# Hardware components used to build the MultiChannelAmp

| Count | Component | Notes |
|---|---|---|
| 1 | Raspberry Pi5 | I decided to use a Pi5 to prevent any issues with USB, CPU or networking performance. |
| 1 | Waveshare Power Over Ethernet HAT G | I use a PoE hat, because I have a PeO switch anyway. Alternatively, use a separate 5V/2,5A power supply |
| 3 | SURE KAB9 USB sound card | Cards can be muted and suspended using two separated connectors. Saves some energy if not in use. |
| 1 | Meanwell HRPG-600-24 | I choosed this model, since multiple power supplies can be combined in case 600W is not enough. Moreover, this power supply can be deactived by the raspberry to save some energy |
| 1 | DC 5v-36v 400W FET Module Board | Used to drive the fan using PWM signal |
| 1 | Sunon MagLev MEC038V2-000U-A99 fan | 24V fan to be able to drive it directly from the power supply |
| 1 | Hailege PC817 8 Channel Optokoppler Module | Resistors are too high for 3,3V of the GPIOs. I removed both, SMD LED and SMD resistor and connected a LED for the case in combination with another resistor |
| 24 | KF2EDGWB | 4-Pin connector named KF2EDGWB at aliexpress |
| x | Misc | LEDs, cable, connectors | 




