# msh_config.py
# version 0.0.1b1
# dude code - alexander lauterbach
# 020924

import json
import time
import paho.mqtt.client as mqttc


def start_mqtt_listener(self):
    """
    Starts the MQTT listener and sets up the connection and message handlers.
    """

    def on_connect(client, userdata, flags, rc):
        """
        Handles the event when the client connects to the MQTT broker.

        Parameters
        ----------
        client : mqtt.Client
            The MQTT client instance.
        userdata : any
            User-defined data of any type.
        flags : dict
            Response flags sent by the broker.
        rc : int
            The connection result.
        """
        print("Connected to MQTT broker at", self.config["MQTT"]["host"])
        client.subscribe(self.config["MQTT"]["topic_pylips"])

    def on_message(client, userdata, msg):
        """
        Handles the event when a message is received from the MQTT broker.

        Parameters
        ----------
        client : mqtt.Client
            The MQTT client instance.
        userdata : any
            User-defined data of any type.
        msg : mqtt.MQTTMessage
            An instance of MQTTMessage, which contains topic, payload, qos, retain.
        """
        try:
            message = json.loads(msg.payload.decode('utf-8'))
        except json.JSONDecodeError:
            return print("Invalid JSON in mqtt message:", msg.payload.decode('utf-8'))

        if "status" in message:
            self.mqtt_update_status(message["status"])
        if "command" in message:
            body = None
            path = ""
            if "body" in message:
                body = message["body"]
            if "path" in message:
                path = message["path"]
            if message["command"] == "get":
                if len(path) == 0:
                    return print("Please provide a 'path' argument")
                self.get(path, self.verbose, 0, False)
            elif message["command"] == "post":
                if len(path) == 0:
                    return print("Please provide a 'path' argument")
                self.post(path, body, self.verbose)
            elif message["command"] != "post" and message["command"] != "get":
                self.run_command(message["command"], body, self.verbose)

    self.mqtt = mqttc.Client()
    self.mqtt.on_connect = on_connect
    self.mqtt.on_message = on_message

    if len(self.config["MQTT"]["user"]) > 0 and len(self.config["MQTT"]["pass"]) > 0:
        self.mqtt.username_pw_set(self.config["MQTT"]["user"], self.config["MQTT"]["pass"])
    if self.config["MQTT"]["TLS"].lower() == "true":
        if len(self.config["MQTT"]["cert_path"].strip()) > 0:
            self.mqtt.tls_set(self.config["MQTT"]["cert_path"])
        else:
            self.mqtt.tls_set()
    self.mqtt.connect(str(self.config["MQTT"]["host"]), int(self.config["MQTT"]["port"]), 60)
    if self.config["DEFAULT"]["mqtt_listen"] == "True" and self.config["DEFAULT"]["mqtt_update"] == "False":
        self.mqtt.loop_forever()
    else:
        self.mqtt.loop_start()


def mqtt_update_status(self, update):
    """
    Publishes an update with TV status over MQTT.

    Parameters
    ----------
    update : dict
        Status update to publish.
    """
    new_status = dict(self.last_status, **update)
    if json.dumps(new_status) != json.dumps(self.last_status):
        self.last_status = new_status
        self.mqtt.publish(str(self.config["MQTT"]["topic_status"]), json.dumps(self.last_status), retain=True)


def mqtt_update_powerstate(self):
    """
    Updates power state for MQTT status.

    Returns
    -------
    bool
        True if the TV is on, False otherwise.
    """
    powerstate_status = self.get("powerstate", self.verbose, 0, False)
    if powerstate_status is not None and powerstate_status[0] == '{':
        powerstate_status = json.loads(powerstate_status)
        if "powerstate" in powerstate_status:
            self.mqtt_update_status({"powerstate": powerstate_status["powerstate"]})
            return powerstate_status["powerstate"] == "On"
    self.mqtt_update_status({"powerstate": "Off"})
    return False


def mqtt_update_ambilight(self):
    """
    Updates ambilight for MQTT status.
    """
    ambilight_status = self.get("ambilight/currentconfiguration", self.verbose, 0, False)
    if ambilight_status is not None and ambilight_status[0] == '{':
        ambilight_status = json.loads(ambilight_status)
        if "styleName" in ambilight_status:
            self.mqtt_update_status({"ambilight": ambilight_status["styleName"]})


def mqtt_update_ambihue(self):
    """
    Updates ambihue for MQTT status.
    """
    ambihue_state = self.run_command("ambihue_state", None, self.verbose, False, False)
    if ambihue_state is not None and ambihue_state[0] == '{':
        ambihue_state = json.loads(ambihue_state)
        if "power" in ambihue_state:
            self.mqtt_update_status({"ambihue": ambihue_state["power"] == "On"})


def mqtt_update_ambilight_brightness_state(self):
    """
    Updates ambilight brightness for MQTT status.
    """
    brightness_status = self.run_command("ambilight_brightness_state", None, self.verbose, False)
    if brightness_status is not None and brightness_status[0] == '{':
        brightness_status = json.loads(brightness_status)
        if "values" in brightness_status:
            self.mqtt_update_status({"ambi_brightness": brightness_status["values"][0]["value"]["data"]})


def mqtt_update_display_light_sensor_state(self):
    """
    Updates display light sensor status for MQTT status.
    """
    dls_state = self.run_command("display_light_sensor_state", None, self.verbose, False)
    if dls_state is not None and dls_state[0] == '{':
        dls_state = json.loads(dls_state)
        if "values" in dls_state:
            self.mqtt_update_status({"dls_state": dls_state["values"][0]["value"]["data"]})


def start_mqtt_updater(self, verbose=True):
    """
    Runs MQTT update functions with a specified update interval.

    Parameters
    ----------
    verbose : bool, optional
        Verbose mode flag (default is True).
    """
    print("Started MQTT status updater")
    while True:
        if self.mqtt_update_powerstate():
            self.mqtt_update_ambilight()
            self.mqtt_update_ambihue()
            self.mqtt_update_ambilight_brightness_state()
            self.mqtt_update_display_light_sensor_state()
        else:
            self.mqtt.publish(str(self.config["MQTT"]["topic_status"]), json.dumps(self.last_status), retain=True)
        time.sleep(int(self.config["DEFAULT"]["update_interval"]))
