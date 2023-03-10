from __future__ import annotations

import logging
import pigpio

import voluptuous as vol

from homeassistant.components.cover import (
    PLATFORM_SCHEMA,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_STOP,
    CoverEntity,
)
from homeassistant.components.number import RestoreNumber
from homeassistant.const import (
    CONF_NAME,
    CONF_UNIQUE_ID,
    CONF_COVERS,
    CONF_FRIENDLY_NAME,
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from .encode_tables import (
    NICE_FLOR_S_TABLE_ENCODE,
    NICE_FLOR_S_TABLE_KI,
)
from threading import Lock
from .const import (
    DOMAIN,
    CONF_SERIAL,
    CONF_START_CODE,
    CONF_GPIO,
    DEVICE_CLASS,
)

_LOGGER = logging.getLogger(__name__)

CONF_GPIO = "gpio"
CONF_SERIAL = "serial"
CONF_PIGPIO_HOST = "pigpio_host"
DEVICE_CLASS = "shutter"

GPIO_NONE = 0
BUTTON_ID_OPEN = 1
BUTTON_ID_STOP = 2
BUTTON_ID_CLOSE = 4

COVER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL): cv.positive_int,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_FRIENDLY_NAME): cv.string,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_GPIO): cv.positive_int,
        vol.Optional(CONF_PIGPIO_HOST, default="localhost"): cv.string,
        vol.Required(CONF_START_CODE): cv.positive_int,
        vol.Required(CONF_COVERS): vol.Schema({cv.string: COVER_SCHEMA}),
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    hass.data.setdefault(DOMAIN, {})

    next_code = NextCodeEntity(config[CONF_START_CODE])
    add_entities([next_code])

    hub = NiceHub(
        hass=hass,
        pigpio_host=config[CONF_PIGPIO_HOST],
        gpio=config[CONF_GPIO],
        next_code=next_code,
    )
    hass.data[DOMAIN] = hub

    devices = []
    for dev_name, properties in config[CONF_COVERS].items():
        devices.append(
            NiceCover(
                hub=hub,
                friendly_name=properties.get(CONF_FRIENDLY_NAME),
                unique_id=properties.get(CONF_NAME, dev_name),
                serial=properties.get(CONF_SERIAL),
            )
        )

    add_entities(devices)
    hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, lambda event: hub.cleanup())

    hass.services.register(
        DOMAIN,
        "pair",
        hub.pair,
        vol.Schema(
            {
                vol.Required(CONF_SERIAL): cv.positive_int,
            }
        ),
    )


class NextCodeEntity(RestoreNumber):
    def __init__(self, start_code: int) -> None:
        self._attr_unique_id = "next_code"
        self._attr_native_value = start_code
        self._attr_icon = "mdi:remote"
        self._attr_name = "Nice Flor-S Next Code"

    def increase(self):
        self._attr_native_value = self._attr_native_value + 1

    async def async_added_to_hass(self) -> None:
        """Load the last known state when added to hass."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) and (
            last_number_data := await self.async_get_last_number_data()
        ):
            if last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._attr_native_value = last_number_data.native_value


class RFDevice:
    def __init__(
        self,
        gpio: int,
        pi: pigpio,
    ) -> None:
        self._pi = pi
        self._gpio = gpio
        self.tx_pulse_short = 500
        self.tx_pulse_long = 1000
        self.tx_pulse_sync = 1500
        self.tx_pulse_gap = 2000
        self.tx_length = 52

    def tx_code(self, code: int):
        wf = []
        wf.extend(self.tx_sync())
        rawcode = format(code, "#0{}b".format(self.tx_length))[2:]
        for bit in range(0, self.tx_length):
            if rawcode[bit] == "1":
                wf.extend(self.tx_l0())
            else:
                wf.extend(self.tx_l1())
        wf.extend(self.tx_sync())
        wf.extend(self.tx_gap())

        self._pi.wave_clear()
        self._pi.wave_add_generic(wf)
        wave = self._pi.wave_create()
        self._pi.wave_send_once(wave)

        while self._pi.wave_tx_busy():
            pass

        self._pi.wave_delete(wave)

    def tx_l0(self):
        return [
            pigpio.pulse(self._gpio, GPIO_NONE, self.tx_pulse_short),
            pigpio.pulse(GPIO_NONE, self._gpio, self.tx_pulse_long),
        ]

    def tx_l1(self):
        return [
            pigpio.pulse(self._gpio, GPIO_NONE, self.tx_pulse_long),
            pigpio.pulse(GPIO_NONE, self._gpio, self.tx_pulse_short),
        ]

    def tx_sync(self):
        return [
            pigpio.pulse(self._gpio, GPIO_NONE, self.tx_pulse_sync),
            pigpio.pulse(GPIO_NONE, self._gpio, self.tx_pulse_sync),
        ]

    def tx_gap(self):
        return [
            pigpio.pulse(GPIO_NONE, self._gpio, self.tx_pulse_gap),
        ]


class PigpioNotConnected(BaseException):
    """"""


class NiceHub:
    def __init__(
        self,
        hass: HomeAssistant,
        pigpio_host: str | None,
        gpio: int,
        next_code: NextCodeEntity,
    ) -> None:
        self._gpio = gpio
        self._next_code = next_code
        self._lock = Lock()

        self._pi = pigpio.pi(pigpio_host)

        if not self._pi.connected:
            raise PigpioNotConnected()

        rfdevice = RFDevice(gpio=1 << gpio, pi=self._pi)
        self._rfdevice = rfdevice

    def cleanup(self):
        with self._lock:
            self._pi.stop()

    def pair(self, service_call: ServiceCall):
        with self._lock:
            button_id = BUTTON_ID_STOP
            code = int(self._next_code.native_value)
            serial = service_call.data[CONF_SERIAL]

            _LOGGER.info("Starting pairing of %s... Wait 5 seconds.", hex(serial))

            for _ in range(1, 10):
                self._send_repeated(serial, button_id, code)

            _LOGGER.info("Entered pairing mode for %s.", hex(serial))

    def send(self, serial: int, button_id: int):
        code = int(self._next_code.native_value)
        self._send_repeated(serial, button_id, code)
        self._next_code.increase()

    def _send_repeated(self, serial: int, button_id: int, code: int):
        with self._lock:
            for repeat in range(1, 7):
                tx_code = self._nice_flor_s_encode(serial, code, button_id, repeat)
                _LOGGER.info(
                    "serial %s, button_id %i, code %i, tx_code %s",
                    hex(serial),
                    button_id,
                    code,
                    hex(tx_code),
                )
                self._rfdevice.tx_code(tx_code)

    def _nice_flor_s_encode(
        self, serial: int, code: int, button_id: int, repeat: int
    ) -> int:
        snbuff = [None] * 4
        snbuff[0] = serial & 0xFF
        snbuff[1] = (serial & 0xFF00) >> 8
        snbuff[2] = (serial & 0xFF0000) >> 16
        snbuff[3] = (serial & 0xFF000000) >> 24

        encbuff = [None] * 7
        enccode = NICE_FLOR_S_TABLE_ENCODE[code]
        ki = NICE_FLOR_S_TABLE_KI[code & 0xFF] ^ (enccode & 0xFF)

        encbuff[0] = button_id & 0x0F
        encbuff[1] = ((repeat ^ button_id ^ 0x0F) << 4) | ((snbuff[3] ^ ki) & 0x0F)
        encbuff[2] = enccode >> 8
        encbuff[3] = enccode & 0xFF
        encbuff[4] = snbuff[2] ^ ki
        encbuff[5] = snbuff[1] ^ ki
        encbuff[6] = snbuff[0] ^ ki

        encoded = 0
        encoded |= ((encbuff[6] << 0x4) & 0xF0) << 0
        encoded |= (((encbuff[5] & 0x0F) << 4) | ((encbuff[6] & 0xF0) >> 4)) << 8
        encoded |= (((encbuff[4] & 0x0F) << 4) | ((encbuff[5] & 0xF0) >> 4)) << 16
        encoded |= (((encbuff[3] & 0x0F) << 4) | ((encbuff[4] & 0xF0) >> 4)) << 24
        encoded |= (((encbuff[2] & 0x0F) << 4) | ((encbuff[3] & 0xF0) >> 4)) << 32
        encoded |= (((encbuff[1] & 0x0F) << 4) | ((encbuff[2] & 0xF0) >> 4)) << 40
        encoded |= (((encbuff[0] & 0x0F) << 4) | ((encbuff[1] & 0xF0) >> 4)) << 48
        encoded = encoded ^ 0xFFFFFFFFFFFFF0
        encoded = encoded >> 4

        return encoded


class NiceCover(CoverEntity):
    def __init__(
        self,
        hub: NiceHub,
        friendly_name: str,
        unique_id: str,
        serial: int,
    ):
        super().__init__()
        self._hub = hub
        self._serial = serial

        self._attr_assumed_state = True
        self._attr_name = friendly_name
        self._attr_unique_id = unique_id
        self._attr_supported_features = SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP
        self._attr_device_class = DEVICE_CLASS
        self._attr_current_cover_position = 50
        self._attr_is_closed = False
        self._attr_is_opening = False
        self._attr_should_poll = False

    def open_cover(self, **kwargs):
        self._hub.send(self._serial, BUTTON_ID_OPEN)

    def close_cover(self, **kwargs):
        self._hub.send(self._serial, BUTTON_ID_CLOSE)

    def stop_cover(self, **kwargs) -> None:
        self._hub.send(self._serial, BUTTON_ID_STOP)
