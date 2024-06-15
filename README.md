<img src="https://www.home-assistant.io/images/home-assistant-logo.svg" alt="Home Assistant" width="200"/><br>
This integration allows you to control Nice Flor-S shutters with a Raspberry Pi and a 433 MHz transmitter.

## Installation 
1. Install the [pigpio addon](https://community.home-assistant.io/t/pigpio-addon/314734) to your Home Assistant instance.
2. Install a file manager addon
3. Create a new directory in `/config` called `custom_components`
4. Create a new directory in `/config/custom_components` called `nice_flor_s`
5. Copy the contents of this repository to `/config/custom_components/nice_flor_s` except for the `configurations` directory
6. Configure the integration in your `configuration.yaml` file (see below)
7. Restart Home Assistant
8. Pair your shutters by calling the service `nice_flor_s.pair` with the serial number of the shutter you want to pair
9. Use the Home Assistant UI to control your shutters (You can add the CoverEntity to your Lovelace dashboard)
## Configuration options
| Key | Type | Required | Description |
| --- | --- | --- | --- |
| `gpio` | `int` | `True` | The GPIO pin where the transmitter is connected |
| `pigpio_host` | `string` | `False` | The hostname of the pigpio instance |
| `start_code` | `int` | `True` | The first code to use for the shutters |
| `covers` | `object` | `True` | The list of shutters to control |
| `covers.<name>` | `object` | `True` | The configuration of a shutter |
| `covers.<name>.serial` | `int` | `True` | The serial number of the shutter |
| `covers.<name>.friendly_name` | `string` | `False` | The friendly name of the shutter |
## Pairing
To pair a shutter, call the service `nice_flor_s.pair` with the serial number of the shutter you want to pair.
The shutter will enter pairing mode for 5 seconds. During this time, press the button on the shutter to pair it.
## Troubleshooting
- Make sure that the pigpio addon is installed and running
- Make sure that the GPIO pin is correctly configured
- Make sure that the transmitter is correctly connected to the GPIO pin
- Make sure that the shutter is in pairing mode
- Make sure that the serial number of the shutter is correct
- Make sure that the code is correctly transmitted
## Issues
If you encounter any issues, please create an issue on GitHub.
## License
This integration is licensed under the MIT License.
