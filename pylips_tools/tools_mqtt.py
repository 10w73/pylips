# msh_config.py
# version 0.0.1b1
# dude code - alexander lauterbach
# 020924

import json
import time


def mqtt_update_powerstate(self):
    """
    Update power state for MQTT status.

    Returns:
        bool: True if TV is on, False otherwise.
    """
    powerstate_status = self.get("powerstate", self.verbose, 0, False)
    if powerstate_status is not None and powerstate_status[0] == '{':
        powerstate_status = json.loads(powerstate_status)
        if "powerstate" in powerstate_status:
            if "powerstate" in self.last_status and self.last_status["powerstate"] != powerstate_status['powerstate']:
                self.mqtt.publish(
                    str(self.config["MQTT"]["topic_pylips"]),
                    json.dumps({"status": {"powerstate": powerstate_status['powerstate']}}),
                    retain=False
                )
            if powerstate_status['powerstate'].lower() == "on":
                return True
        else:
            self.mqtt_update_status(
                {
                    "powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                    "dls_state": False
                }
            )
    else:
        self.mqtt_update_status(
            {
                "powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                "dls_state": False
            }
        )
    return False


def mqtt_update_ambilight(self):
    """
    Update ambilight for MQTT status.
    """
    ambilight_status = self.get("ambilight/currentconfiguration", self.verbose, 0, False)
    if ambilight_status is not None and ambilight_status[0] == '{':
        ambilight_status = json.loads(ambilight_status)
        if "styleName" in ambilight_status:
            ambilight = ambilight_status
            if json.dumps(self.last_status["ambilight"]) != json.dumps(ambilight):
                self.mqtt.publish(
                    str(self.config["MQTT"]["topic_pylips"]), json.dumps(
                        {
                            "status": {
                                "ambilight": ambilight
                            }
                        }
                    ), retain=False
                )


def mqtt_update_ambihue(self):
    """
    Update ambihue for MQTT status.
    """
    ambihue_state = self.run_command("ambihue_state", None, self.verbose, False, False)
    if ambihue_state is not None and ambihue_state[0] == '{':
        ambihue_state = json.loads(ambihue_state)
        if "power" in ambihue_state:
            ambihue = ambihue_state["power"]
            if self.last_status["ambihue"] != ambihue:
                self.mqtt.publish(
                    str(self.config["MQTT"]["topic_pylips"]), json.dumps(
                        {
                            "status": {
                                "ambihue": ambihue
                            }
                        }
                    ), retain=False
                )


def mqtt_update_ambilight_brightness_state(self):
    """
    Update ambilight brightness for MQTT status.
    """
    brightness_status = self.run_command("ambilight_brightness_state", None, self.verbose, False)
    if brightness_status is not None and brightness_status[0] == '{':
        brightness_status = json.loads(brightness_status)
        if "values" in brightness_status:
            ambi_brightness = brightness_status["values"][0]["value"]["data"]["value"]
            if self.last_status["ambi_brightness"] != ambi_brightness:
                self.mqtt.publish(
                    str(self.config["MQTT"]["topic_pylips"]),
                    json.dumps({"status": {"ambi_brightness": ambi_brightness}}), retain=False
                )


def mqtt_update_display_light_sensor_state(self):
    """
    Update display light sensor status for MQTT status.
    """
    dls_state = self.run_command("display_light_sensor_state", None, self.verbose, False)
    if dls_state is not None and dls_state[0] == '{':
        dls_state = json.loads(dls_state)
        if "values" in dls_state:
            dls = dls_state["values"][0]["value"]["data"]["selected_item"]
            print(dls)
            if self.last_status["dls_state"] != dls:
                self.mqtt.publish(
                    str(self.config["MQTT"]["topic_pylips"]),
                    json.dumps({"status": {"dls_state": dls}}), retain=False
                )


def start_mqtt_updater(self, verbose=True):
    """
    Run MQTT update functions with a specified update interval.

    Args:
        verbose (bool): Display feedback.
    """
    print("Started MQTT status updater")
    while True:
        if self.mqtt_update_powerstate():
            self.mqtt_update_ambilight()
            self.mqtt_update_ambihue()
            self.mqtt_update_ambilight_brightness_state()
            self.mqtt_update_display_light_sensor_state()
        else:
            self.mqtt.publish(
                str(self.config["MQTT"]["topic_status"]),
                json.dumps(
                    {
                        "powerstate": "Off", "ambilight": False, "ambihue": False,
                        "ambi_brightness": False, "dls_state": False
                    }
                ), retain=False
            )
        time.sleep(int(self.config["DEFAULT"]["update_interval"]))
