# dev version 1.3.2 - version 1.4.0a1
# dude-code - alexander lauterbach
# 010924

import configparser
import requests
import json
import time
import argparse
import sys
from requests.auth import HTTPDigestAuth
import paho.mqtt.client as mqttc
import os

# Suppress "Unverified HTTPS request is being made" error message
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
session = requests.Session()
session.verify = False
session.mount('https://', requests.adapters.HTTPAdapter(pool_connections=1))

parser = argparse.ArgumentParser(description="Control Philips TV API (versions 5 and 6)")
parser.add_argument("--host", dest="host", help="TV's ip address")
parser.add_argument("--user", dest="user", help="Username")
parser.add_argument("--pass", dest="password", help="Password")
parser.add_argument("--command", help="Command to run", default="")
parser.add_argument("--path", dest="path", help="API's endpoint path")
parser.add_argument("--body", dest="body", help="Body for post requests")
parser.add_argument("--verbose", dest="verbose", help="Display feedback")
parser.add_argument("--apiv", dest="apiv", help="Api version", default="")
parser.add_argument("--config", dest="config", help="Path to config file",
                    default=os.path.dirname(os.path.realpath(__file__)) + os.path.sep + "settings.ini")

args = parser.parse_args()


class Pylips:
    def __init__(self, ini_file):
        """
        Initialize the Pylips class, load the configuration file, and set up initial parameters.

        :param ini_file: Path to the configuration file
        :type ini_file: str
        :raises FileNotFoundError: If the config file is not found
        :raises IOError: If the config file cannot be read
        :raises ValueError: If TV's IP-address is not set in either command-line args or the config file
        """
        self.config = self._load_config(ini_file)
        self.verbose = self._get_verbose_option()
        self._override_config_with_args()
        self.available_commands = self._load_available_commands()

        if self.config["MQTT"]["host"]:
            self._start_mqtt_services()
        else:
            print("Please specify host in MQTT section in settings.ini to use MQTT")

        self._parse_and_run_command()

    def _load_config(self, ini_file):
        """
        Load and parse the configuration file.

        :param ini_file: Path to the configuration file
        :type ini_file: str
        :raises FileNotFoundError: If the config file is not found
        :raises IOError: If the config file cannot be read
        :return: Parsed configuration
        :rtype: configparser.ConfigParser
        """
        config = configparser.ConfigParser()
        if not os.path.isfile(ini_file):
            raise FileNotFoundError(f"Config file {ini_file} not found")

        try:
            config.read(ini_file)
        except Exception as e:
            raise IOError(f"Config file {ini_file} found, but cannot be read: {e}")

        if not args.host and not config["TV"]["host"]:
            raise ValueError(
                "Please set your TV's IP-address with a --host parameter or in [TV] section in settings.ini")

        return config

    def _get_verbose_option(self):
        """
        Retrieve the verbose option from the configuration.

        :return: Verbose flag
        :rtype: bool
        """
        return self.config["DEFAULT"].getboolean("verbose")

    def _override_config_with_args(self):
        """
        Override configuration settings with command-line arguments if provided.
        """
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

    def _load_available_commands(self):
        """
        Load available API commands from a JSON file.

        :return: Available API commands
        :rtype: dict
        """
        commands_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "available_commands.json")
        with open(commands_file) as json_file:
            return json.load(json_file)

    def _start_mqtt_services(self):
        """
        Start MQTT listener and updater services.
        """
        self.start_mqtt_listener()
        self.last_status = {
            "powerstate": None,
            "ambilight": False,
            "ambihue": False,
            "ambi_brightness": False,
            "dls_state": False
        }
        self.start_mqtt_updater(self.verbose)

    def _parse_and_run_command(self):
        """
        Parse the command-line arguments and execute the corresponding command.
        """
        body = args.body
        path = args.path

        if args.command == "get":
            self.get(path, self.verbose)
        elif args.command == "post":
            self.post(path, body, self.verbose)
        elif args.command:
            self.run_command(args.command, body, self.verbose)
        else:
            print("Please provide a valid command with a '--command' argument")

    def get(self, path, verbose=True, err_count=0, print_response=True):
        """
        Send a GET request to the TV's API.

        :param path: API path for the GET request
        :type path: str
        :param verbose: Verbose output flag, defaults to True
        :type verbose: bool, optional
        :param err_count: Error retry counter, defaults to 0
        :type err_count: int, optional
        :param print_response: Flag to print the response, defaults to True
        :type print_response: bool, optional
        :return: Response text or error message in JSON format
        :rtype: str
        """
        while err_count < int(self.config["DEFAULT"]["num_retries"]):
            if verbose:
                print("Sending GET request to",
                      f"{self.config['TV']['protocol']}{self.config['TV']['host']}:{self.config['TV']['port']}/{self.config['TV']['apiv']}/{path}")
            try:
                r = session.get(
                    f"{self.config['TV']['protocol']}{self.config['TV']['host']}:{self.config['TV']['port']}/{self.config['TV']['apiv']}/{path}",
                    verify=False, auth=HTTPDigestAuth(self.config["TV"]["user"], self.config["TV"]["pass"]), timeout=2)
            except Exception:
                err_count += 1
                continue
            if verbose:
                print("Request sent!")
            if r.text:
                if print_response:
                    print(r.text)
                return r.text
        else:
            if self.config["DEFAULT"].getboolean("mqtt_listen"):
                self.mqtt_update_status(
                    {"powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                     "dls_state": False})
            return json.dumps({"error": "Can not reach the API"})

    def post(self, path, body, verbose=True, callback=True, err_count=0):
        """
        Send a POST request to the TV's API.

        :param path: API path for the POST request
        :type path: str
        :param body: Request body content
        :type body: str or dict
        :param verbose: Verbose output flag, defaults to True
        :type verbose: bool, optional
        :param callback: Callback function flag, defaults to True
        :type callback: bool, optional
        :param err_count: Error retry counter, defaults to 0
        :type err_count: int, optional
        :return: Response text or error message in JSON format
        :rtype: str
        """
        while err_count < int(self.config["DEFAULT"]["num_retries"]):
            if isinstance(body, str):
                body = json.loads(body)
            if verbose:
                print("Sending POST request to",
                      f"{self.config['TV']['protocol']}{self.config['TV']['host']}:{self.config['TV']['port']}/{self.config['TV']['apiv']}/{path}")
            try:
                r = session.post(
                    f"{self.config['TV']['protocol']}{self.config['TV']['host']}:{self.config['TV']['port']}/{self.config['TV']['apiv']}/{path}",
                    json=body, verify=False, auth=HTTPDigestAuth(self.config["TV"]["user"], self.config["TV"]["pass"]),
                    timeout=2)
            except Exception:
                err_count += 1
                continue
            if verbose:
                print("Request sent!")
            # if callback and self.config["DEFAULT"].getboolean("mqtt_listen") and len(sys.argv) == 1:
            #     self.mqtt_callback(path)
            if r.text:
                print(r.text)
                return r.text
            elif r.status_code == 200:
                print(json.dumps({"response": "OK"}))
                return json.dumps({"response": "OK"})
        else:
            if self.config["DEFAULT"].getboolean("mqtt_listen") and len(sys.argv) == 1:
                self.mqtt_update_status(
                    {"powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                     "dls_state": False})
            print(json.dumps({"error": "Can not reach the API"}))
            return json.dumps({"error": "Can not reach the API"})

    def run_command(self, command, body=None, verbose=True, callback=True, print_response=True):
        """
        Execute a command by determining its type (GET, POST, or power) and sending the appropriate request.

        :param command: The command to be executed
        :type command: str
        :param body: The request body, defaults to None
        :type body: str or dict, optional
        :param verbose: Verbose output flag, defaults to True
        :type verbose: bool, optional
        :param callback: Callback function flag, defaults to True
        :type callback: bool, optional
        :param print_response: Flag to print the response, defaults to True
        :type print_response: bool, optional
        :return: API response or None
        :rtype: str or None
        """
        if command in self.available_commands["get"]:
            return self.get(self.available_commands["get"][command]["path"], verbose, 0, print_response)
        elif command in self.available_commands["post"]:
            body = self._prepare_post_body(command, body)
            return self.post(self.available_commands["post"][command]["path"], body, verbose, callback)
        elif command in self.available_commands["power"]:
            return session.post(
                f"http://{self.config['TV']['host']}:8008/{self.available_commands['power'][command]['path']}",
                verify=False, timeout=2)
        else:
            print("Unknown command")

    def _prepare_post_body(self, command, body):
        """
        Prepare the body for a POST request based on the command.

        :param command: The command to be executed
        :type command: str
        :param body: The request body, defaults to None
        :type body: str or dict, optional
        :return: Prepared request body
        :rtype: dict
        """
        if "body" in self.available_commands["post"][command] and body is None:
            return self.available_commands["post"][command]["body"]
        elif "body" in self.available_commands["post"][command] and body is not None:
            if isinstance(body, str):
                body = json.loads(body)
            new_body = self.available_commands["post"][command]["body"]
            if command == "ambilight_brightness":
                new_body["values"][0]["value"]["data"] = body
            elif command == "ambilight_color":
                new_body["colorSettings"]["color"]["hue"] = int(body["hue"] * (255 / 360))
                new_body["colorSettings"]["color"]["saturation"] = int(body["saturation"] * (255 / 100))
                new_body["colorSettings"]["color"]["brightness"] = int(body["brightness"])
            elif command == "google_assistant":
                new_body["intent"]["extras"]["query"] = body["query"]
            elif "input_" in command:
                new_body = self.available_commands["google_assistant"][command]
                new_body["intent"]["extras"]["query"] = self.available_commands["post"][command]["body"]["query"]
            return new_body
        return body

    # def mqtt_callback(self, path):
    #     """
    #     MQTT callback for handling specific path updates.
    #
    #     :param path: The path from the MQTT message
    #     :type path: str
    #     """
    #     if "ambilight" or "ambihue" or "ambi_brightness" in path:
    #         self.mqtt_update_ambilight()
    #         self.mqtt_update_ambihue()
    #         self.mqtt_update_ambilight_brightness_state()

    def start_mqtt_listener(self):
        """
        Start the MQTT listener to listen for messages and execute commands based on the received payloads.
        """

        def on_connect(client, userdata, flags, rc):
            print(f"Connected to MQTT broker at {self.config['MQTT']['host']}")
            client.subscribe(self.config["MQTT"]["topic_pylips"])

        def on_message(client, userdata, msg):
            self._handle_mqtt_message(msg)

        self.mqtt = mqttc.Client()
        self.mqtt.on_connect = on_connect
        self.mqtt.on_message = on_message
        self.mqtt.connect(self.config["MQTT"]["host"], int(self.config["MQTT"]["port"]), 60)
        self.mqtt.loop_start()

    def _handle_mqtt_message(self, msg):
        """
        Handle incoming MQTT messages.

        :param msg: The MQTT message object
        :type msg: mqtt.MQTTMessage
        """
        if msg.topic == self.config["MQTT"]["topic_pylips"]:
            try:
                message = json.loads(msg.payload.decode('utf-8'))
            except json.JSONDecodeError:
                print(f"Invalid JSON in mqtt message: {msg.payload.decode('utf-8')}")
                return
            if "status" in message:
                self.mqtt_update_status(message["status"])
            if "command" in message:
                body = message.get("body")
                path = message.get("path", "")
                if message["command"] == "get":
                    if not path:
                        print("Please provide a 'path' argument")
                        return
                    self.get(path, self.verbose, 0, False)
                elif message["command"] == "post":
                    if not path:
                        print("Please provide a 'path' argument")
                        return
                    self.post(path, body, self.verbose)
                else:
                    self.run_command(message["command"], body, self.verbose)

    def mqtt_update_status(self, update):
        """
        Update the MQTT status with the provided update.

        :param update: Dictionary containing the status update
        :type update: dict
        """
        new_status = dict(self.last_status, **update)
        if json.dumps(new_status) != json.dumps(self.last_status):
            self.last_status = new_status
            self.mqtt.publish(self.config["MQTT"]["topic_status"], json.dumps(self.last_status), retain=True)

    def mqtt_update_powerstate(self):
        """
        Update the power state via MQTT.

        :return: True if the TV is on, otherwise False
        :rtype: bool
        """
        powerstate_status = self.get("powerstate", self.verbose, 0, False)
        if powerstate_status and powerstate_status[0] == '{':
            powerstate_status = json.loads(powerstate_status)
            if "powerstate" in powerstate_status:
                if "powerstate" in self.last_status and self.last_status["powerstate"] != powerstate_status[
                    'powerstate']:
                    self.mqtt.publish(self.config["MQTT"]["topic_pylips"],
                                      json.dumps({"status": {"powerstate": powerstate_status['powerstate']}}),
                                      retain=False)
                if powerstate_status['powerstate'].lower() == "on":
                    return True
            else:
                self.mqtt_update_status(
                    {"powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                     "dls_state": False})
        else:
            self.mqtt_update_status(
                {"powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                 "dls_state": False})
        return False

    def mqtt_update_ambilight(self):
        """
        Update the ambilight status via MQTT.
        """
        ambilight_status = self.get("ambilight/currentconfiguration", self.verbose, 0, False)
        if ambilight_status and ambilight_status[0] == '{':
            ambilight_status = json.loads(ambilight_status)
            if "styleName" in ambilight_status:
                ambilight = ambilight_status
                if json.dumps(self.last_status["ambilight"]) != json.dumps(ambilight):
                    self.mqtt.publish(self.config["MQTT"]["topic_pylips"],
                                      json.dumps({"status": {"ambilight": ambilight}}), retain=False)

    def mqtt_update_ambihue(self):
        """
        Update the ambihue status via MQTT.
        """
        ambihue_state = self.run_command("ambihue_state", None, self.verbose, False, False)
        if ambihue_state and ambihue_state[0] == '{':
            ambihue_state = json.loads(ambihue_state)
            if "power" in ambihue_state:
                ambihue = ambihue_state["power"]
                if self.last_status["ambihue"] != ambihue:
                    self.mqtt.publish(self.config["MQTT"]["topic_pylips"], json.dumps({"status": {"ambihue": ambihue}}),
                                      retain=False)

    def mqtt_update_ambilight_brightness_state(self):
        """
        Update the ambilight brightness state via MQTT.
        """
        brightness_status = self.run_command("ambilight_brightness_state", None, self.verbose, False)
        if brightness_status and brightness_status[0] == '{':
            brightness_status = json.loads(brightness_status)
            if "values" in brightness_status:
                ambi_brightness = brightness_status["values"][0]["value"]["data"]["value"]
                if self.last_status["ambi_brightness"] != ambi_brightness:
                    self.mqtt.publish(self.config["MQTT"]["topic_pylips"],
                                      json.dumps({"status": {"ambi_brightness": ambi_brightness}}), retain=False)

    def mqtt_update_display_light_sensor_state(self):
        """
        Update the display light sensor state via MQTT.
        """
        dls_state = self.run_command("display_light_sensor_state", None, self.verbose, False)
        if dls_state and dls_state[0] == '{':
            dls_state = json.loads(dls_state)
            if "values" in dls_state:
                dls = dls_state["values"][0]["value"]["data"]["selected_item"]
                print(dls)
                if self.last_status["dls_state"] != dls:
                    self.mqtt.publish(self.config["MQTT"]["topic_pylips"], json.dumps({"status": {"dls_state": dls}}),
                                      retain=False)

    def start_mqtt_updater(self, verbose=True):
        """
        Start the MQTT updater to periodically update the status of the TV.

        :param verbose: Verbose output flag, defaults to True
        :type verbose: bool, optional
        """
        print("Started MQTT status updater")
        while True:
            if self.mqtt_update_powerstate():
                self.mqtt_update_ambilight()
                self.mqtt_update_ambihue()
                self.mqtt_update_ambilight_brightness_state()
                self.mqtt_update_display_light_sensor_state()
            else:
                self.mqtt.publish(self.config["MQTT"]["topic_status"], json.dumps(
                    {"powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                     "dls_state": False}), retain=False)
            time.sleep(int(self.config["DEFAULT"]["update_interval"]))


if __name__ == '__main__':
    pylips = Pylips(args.config)
