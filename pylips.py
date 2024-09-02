# pylips.py
# version 2.0.0a4
# dude code - alexander lauterbach
# 020924

import configparser
import json
import argparse
import sys
import requests
from requests.auth import HTTPDigestAuth
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3 import disable_warnings
import paho.mqtt.client as mqttc
import os
import logging
from pylips_tools.tools_mqtt import (
    start_mqtt_updater,
    mqtt_update_powerstate,
    mqtt_update_ambilight,
    mqtt_update_ambihue,
    mqtt_update_ambilight_brightness_state,
    mqtt_update_display_light_sensor_state
)

# Set up logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up the requests session and disable SSL warnings
disable_warnings(InsecureRequestWarning)

session = requests.Session()
session.verify = False
session.mount('https://', HTTPAdapter(pool_connections=1))

# Set up the argument parser
parser = argparse.ArgumentParser(description="Control Philips TV API (versions 5 and 6)")
parser.add_argument("--host", dest="host", help="TV's ip address")
parser.add_argument("--user", dest="user", help="Username")
parser.add_argument("--pass", dest="password", help="Password")
parser.add_argument("--command", help="Command to run", default="")
parser.add_argument("--path", dest="path", help="API's endpoint path")
parser.add_argument("--body", dest="body", help="Body for post requests")
parser.add_argument("--verbose", dest="verbose", help="Display feedback")
parser.add_argument("--apiv", dest="apiv", help="Api version", default="")
parser.add_argument(
    "--config", dest="config", help="Path to config file",
    default=os.path.dirname(os.path.realpath(__file__)) + os.path.sep + "settings.ini"
)

args = parser.parse_args()


class Pylips:
    def __init__(self, ini_file):
        """
        Initialize the Pylips class.

        Args:
            ini_file (str): Path to the configuration file.

        Returns:
            None
        """
        self.mqtt = None
        self.config = configparser.ConfigParser()

        if not os.path.isfile(ini_file):
            logging.error("Config file %s not found", ini_file)
            return

        try:
            self.config.read(ini_file)
        except configparser.Error:
            logging.error("Config file %s found, but cannot be read", ini_file)
            return

        if args.host is None and self.config["TV"]["host"] == "":
            logging.error(
                "Please set your TV's IP-address with a --host parameter or in [TV] section in settings.ini"
            )
            return

        self.verbose = self.config["DEFAULT"]["verbose"].lower() == "true"

        self.last_status = {
            "powerstate": "Off",
            "ambilight": False,
            "ambihue": False,
            "ambi_brightness": False,
            "dls_state": False
        }

        if len(sys.argv) > 1:
            if args.verbose is not None:
                self.verbose = args.verbose.lower() == "true"
            if args.host:
                self.config["TV"]["host"] = args.host
            if args.user and args.password:
                self.config["TV"]["user"] = args.user
                self.config["TV"]["pass"] = args.password
                self.config["TV"]["port"] = "1926"
                self.config["TV"]["protocol"] = "https://"
            elif (len(self.config["TV"]["user"]) == 0 or len(self.config["TV"]["pass"]) == 0) and self.config["TV"][
                "port"
            ] == "1926":
                logging.error(
                    "If you have an Android TV, please provide both a username and a password (--user and --pass)"
                )
                return
            if len(args.apiv) != 0:
                self.config["TV"]["apiv"] = args.apiv

        with open(os.path.dirname(os.path.realpath(__file__)) + "/available_commands.json") as json_file:
            self.available_commands = json.load(json_file)

        if (len(sys.argv) == 1 or (len(sys.argv) == 3 and sys.argv[1] == "--config")) and self.config["DEFAULT"][
            "mqtt_listen"
        ] == "True":
            if len(self.config["MQTT"]["host"]) > 0:
                self.start_mqtt_listener()
                if self.config["DEFAULT"]["mqtt_update"] == "True":
                    start_mqtt_updater(self)
            else:
                logging.error("Please specify host in MQTT section in settings.ini to use MQTT")
        elif len(sys.argv) > 1:
            body = args.body
            path = args.path
            if args.command == "get":
                self.get(path, self.verbose)
            elif args.command == "post":
                self.post(path, body, self.verbose)
            elif len(args.command) > 0:
                self.run_command(args.command, body, self.verbose)
            else:
                logging.error("Please provide a valid command with a '--command' argument")
        else:
            logging.error(
                "Please enable mqtt_listen in settings.ini or provide a valid command with a '--command' argument"
            )

    def get(self, path, verbose=True, err_count=0, print_response=True):
        """
        Send a GET request to the specified path.

        Args:
            path (str): API endpoint path.
            verbose (bool): Display feedback.
            err_count (int): Number of retry attempts.
            print_response (bool): Print the response.

        Returns:
            str: Response text or error message.
        """
        while err_count < int(self.config["DEFAULT"]["num_retries"]):
            if verbose:
                logging.info(
                    "Sending GET request to %s",
                    str(self.config["TV"]["protocol"]) + str(self.config["TV"]["host"]) + ":" + str(
                        self.config["TV"]["port"]
                    ) + "/" + str(self.config["TV"]["apiv"]) + "/" + str(path)
                )
            try:
                r = session.get(
                    str(self.config["TV"]["protocol"]) + str(self.config["TV"]["host"]) + ":" + str(
                        self.config["TV"]["port"]
                    ) + "/" + str(self.config["TV"]["apiv"]) + "/" + str(path), verify=False,
                    auth=HTTPDigestAuth(str(self.config["TV"]["user"]), str(self.config["TV"]["pass"])),
                    timeout=2
                )
            except Exception as e:
                logging.error("GET request failed: %s", e)
                err_count += 1
                continue
            if verbose:
                logging.info("Request sent!")
            if len(r.text) > 0:
                if print_response:
                    logging.info("Response: %s", r.text)
                if path == "powerstate":
                    logging.info("Powerstate Response: %s", r.text)
                elif path == "ambilight/currentconfiguration":
                    logging.info("Ambilight Response: %s", r.text)
                return r.text
        else:
            if self.config["DEFAULT"]["mqtt_listen"].lower() == "true":
                self.mqtt_update_status(
                    {
                        "powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                        "dls_state": False
                    }
                )
            return json.dumps({"error": "Can not reach the API"})

    def post(self, path, body, verbose=True, err_count=0):
        """
        Send a POST request to the specified path.

        Args:
            path (str): API endpoint path.
            body (str): Request body.
            verbose (bool): Display feedback.
            err_count (int): Number of retry attempts.

        Returns:
            str: Response text or error message.
        """
        while err_count < int(self.config["DEFAULT"]["num_retries"]):
            if type(body) is str:
                body = json.loads(body)
            if verbose:
                logging.info(
                    "Sending POST request to %s",
                    str(self.config["TV"]["protocol"]) + str(self.config["TV"]["host"]) + ":" + str(
                        self.config["TV"]["port"]
                    ) + "/" + str(self.config["TV"]["apiv"]) + "/" + str(path)
                )
            try:
                r = session.post(
                    str(self.config["TV"]["protocol"]) + str(self.config["TV"]["host"]) + ":" + str(
                        self.config["TV"]["port"]
                    ) + "/" + str(self.config["TV"]["apiv"]) + "/" + str(path), json=body,
                    verify=False,
                    auth=HTTPDigestAuth(str(self.config["TV"]["user"]), str(self.config["TV"]["pass"])),
                    timeout=2
                )
            except Exception as e:
                logging.error("POST request failed: %s", e)
                err_count += 1
                continue
            if verbose:
                logging.info("Request sent!")
            if len(r.text) > 0:
                logging.info("Response: %s", r.text)
                return r.text
            elif r.status_code == 200:
                logging.info("Response: OK")
                return json.dumps({"response": "OK"})
        else:
            if self.config["DEFAULT"]["mqtt_listen"].lower() == "true" and len(sys.argv) == 1:
                self.mqtt_update_status(
                    {
                        "powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                        "dls_state": False
                    }
                )
            logging.error("Can not reach the API")
            return json.dumps({"error": "Can not reach the API"})

    def run_command(self, command, body=None, new_body=None, verbose=True, callback=True, print_response=True):
        """
        Run a specified command.

        Args:
            command (str): Command to run.
            body (str, optional): Request body.
            new_body (str, optional): New request body.
            verbose (bool): Display feedback.
            callback (bool): Callback function.
            print_response (bool): Print the response.

        Returns:
            str: Response text or error message.
        """
        if command in self.available_commands["get"]:
            return self.get(self.available_commands["get"][command]["path"], verbose, 0, print_response)
        elif command in self.available_commands["post"]:
            if "body" in self.available_commands["post"][command] and body is None:
                if "input_" in command:
                    body = self.available_commands["post"]["google_assistant"]["body"]
                    path = self.available_commands["post"]["google_assistant"]["path"]
                    body["intent"]["extras"]["query"] = self.available_commands["post"][command]["body"]["query"]
                else:
                    body = self.available_commands["post"][command]["body"]
                    path = self.available_commands["post"][command]["path"]
                return self.post(path, body, verbose, callback)
            if "body" in self.available_commands["post"][command] and body is not None:
                if type(body) is str:
                    body = json.loads(body)
                new_body = self.available_commands["post"][command]["body"]
                if command == "ambilight_brightness":
                    new_body["values"][0]["value"]["data"] = body
            elif command == "ambilight_color":
                if isinstance(body, str):
                    body = json.loads(body)
                if isinstance(body, dict):
                    new_body = {}
                    new_body["colorSettings"]["color"]["hue"] = int(float(body["hue"]) * (255 / 360))
                    new_body["colorSettings"]["color"]["saturation"] = int(float(body["saturation"]) * (255 / 100))
                    new_body["colorSettings"]["color"]["brightness"] = int(float(body["brightness"]))
            elif command == "google_assistant":
                if isinstance(body, str):
                    body = json.loads(body)
                if isinstance(body, dict):
                    new_body = {}
                    new_body["intent"]["extras"]["query"] = str(body["query"])
                elif "input_" in command:
                    new_body = self.available_commands["google_assistant"][command]
                    new_body["intent"]["extras"]["query"] = self.available_commands["post"][command]["body"][
                        "query"]
                return self.post(self.available_commands["post"][command]["path"], new_body, verbose, callback)
            else:
                if body is None:
                    body = "{}"  # Initialize body as an empty JSON string if it is None
                return self.post(self.available_commands["post"][command]["path"], body, verbose, callback)

        elif command in self.available_commands["power"]:
            try:
                return session.post(
                    "http://" + str(self.config["TV"]["host"]) + ":8008/" +
                    self.available_commands["power"][command][
                        "path"], verify=False, timeout=10
                )
            except requests.exceptions.ReadTimeout:
                logging.error("Request timed out. Retrying...")
                return session.post(
                    "http://" + str(self.config["TV"]["host"]) + ":8008/" +
                    self.available_commands["power"][command][
                        "path"], verify=False, timeout=10
                )
        else:
            logging.error("Unknown command")

    def start_mqtt_listener(self):
        """
        Start the MQTT listener.

        Returns:
            None
        """

        def on_connect(client, userdata, flags, rc):
            """
            Handle MQTT connection event.

            Args:
                client: MQTT client instance.
                userdata: User data.
                flags: Connection flags.
                rc: Connection result code.

            Returns:
                None
            """
            logging.info("Connected to MQTT broker at %s", self.config["MQTT"]["host"])
            client.subscribe(self.config["MQTT"]["topic_pylips"])

        def on_message(client, userdata, msg):
            """
            Handle MQTT message event.

            Args:
                client: MQTT client instance.
                userdata: User data.
                msg: MQTT message.

            Returns:
                None
            """
            if str(msg.topic) == self.config["MQTT"]["topic_pylips"]:
                try:
                    message = json.loads(msg.payload.decode('utf-8'))
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
                                return logging.error("Please provide a 'path' argument")
                            self.get(path, self.verbose, 0, False)
                        elif message["command"] == "post":
                            if len(path) == 0:
                                return logging.error("Please provide a 'path' argument")
                            self.post(path, body, self.verbose)
                        elif message["command"] != "post" and message["command"] != "get":
                            self.run_command(message["command"], body, self.verbose)
                except json.JSONDecodeError:
                    return logging.error("Invalid JSON in mqtt message: %s", msg.payload.decode('utf-8'))

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
        Update the MQTT status.

        Args:
            update (dict): Status update.

        Returns:
            None
        """
        new_status = dict(self.last_status, **update)
        if json.dumps(new_status) != json.dumps(self.last_status):
            self.last_status = new_status
            self.mqtt.publish(str(self.config["MQTT"]["topic_status"]), json.dumps(self.last_status), retain=True)

    def start_mqtt_updater(self, verbose=True):
        """
        Start the MQTT updater.

        Args:
            verbose (bool): Display feedback.

        Returns:
            None
        """
        return start_mqtt_updater(self, verbose)

    def mqtt_update_powerstate(self):
        """
        Update the power state for MQTT status.

        Returns:
            None
        """
        return mqtt_update_powerstate(self)

    def mqtt_update_ambilight(self):
        """
        Update the ambilight for MQTT status.

        Returns:
            None
        """
        return mqtt_update_ambilight(self)

    def mqtt_update_ambihue(self):
        """
        Update the ambihue for MQTT status.

        Returns:
            None
        """
        return mqtt_update_ambihue(self)

    def mqtt_update_ambilight_brightness_state(self):
        """
        Update the ambilight brightness for MQTT status.

        Returns:
            None
        """
        return mqtt_update_ambilight_brightness_state(self)

    def mqtt_update_display_light_sensor_state(self):
        """
        Update the display light sensor state for MQTT status.

        Returns:
            None
        """
        return mqtt_update_display_light_sensor_state(self)


if __name__ == '__main__':
    pylips = Pylips(args.config)
