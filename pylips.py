# msh_config.py
# version 2.0.0a1
# dude code - alexander lauterbach
# 020924

import platform
import subprocess
import configparser
import json
import argparse
import sys
import requests
from requests.auth import HTTPDigestAuth
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3 import disable_warnings
import os
from pylips_tools import tools_mqtt

# Set up the requests session and disable warnings
disable_warnings(InsecureRequestWarning)

session = requests.Session()
session.verify = False
session.mount('https://', HTTPAdapter(pool_connections=1))

# Parse command line arguments
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


# Define the Pylips class
class Pylips:
    """
    A class to control Philips TV API.

    Attributes
    ----------
    config : configparser.ConfigParser
        Configuration settings for the TV and MQTT.
    verbose : bool
        Verbose mode flag.
    last_status : dict
        Last known status of the TV.

    Methods
    -------
    is_online(host)
        Checks if the host is online.
    get(path, verbose=True, err_count=0, print_response=True)
        Sends a GET request to the TV API.
    post(path, body, verbose=True, callback=True, err_count=0)
        Sends a POST request to the TV API.
    run_command(command, body=None, verbose=True, callback=True, print_response=True)
        Runs a command on the TV.
    start_mqtt_listener()
        Starts the MQTT listener.
    mqtt_update_status(update)
        Publishes an update with TV status over MQTT.
    mqtt_update_powerstate()
        Updates power state for MQTT status.
    mqtt_update_ambilight()
        Updates ambilight for MQTT status.
    mqtt_update_ambihue()
        Updates ambihue for MQTT status.
    mqtt_update_ambilight_brightness_state()
        Updates ambilight brightness for MQTT status.
    mqtt_update_display_light_sensor_state()
        Updates display light sensor status for MQTT status.
    start_mqtt_updater(verbose=True)
        Runs MQTT update functions with a specified update interval.
    """

    def __init__(self, ini_file):
        """
        Initializes the Pylips class with the given configuration file.

        Parameters
        ----------
        ini_file : str
            Path to the configuration file.
        """
        self.config = configparser.ConfigParser()

        if not os.path.isfile(ini_file):
            print("Config file", ini_file, "not found")
            return

        try:
            self.config.read(ini_file)
        except configparser.Error:
            print("Config file", ini_file, "found, but cannot be read")
            return

        if args.host is None and self.config["TV"]["host"] == "":
            print("Please set your TV's IP-address with a --host parameter or in [TV] section in settings.ini")
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
                "port"] == "1926":
                print("If you have an Android TV, please provide both a username and a password (--user and --pass)")
                return
            if len(args.apiv) != 0:
                self.config["TV"]["apiv"] = args.apiv

        with open(os.path.dirname(os.path.realpath(__file__)) + "/available_commands.json") as json_file:
            self.available_commands = json.load(json_file)

        if (len(sys.argv) == 1 or (len(sys.argv) == 3 and sys.argv[1] == "--config")) and self.config["DEFAULT"][
            "mqtt_listen"] == "True":
            if len(self.config["MQTT"]["host"]) > 0:
                self.start_mqtt_listener()
                if self.config["DEFAULT"]["mqtt_update"] == "True":
                    tools_mqtt.start_mqtt_updater(self)
            else:
                print("Please specify host in MQTT section in settings.ini to use MQTT")
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
                print("Please provide a valid command with a '--command' argument")
        else:
            print("Please enable mqtt_listen in settings.ini or provide a valid command with a '--command' argument")

    def is_online(self, host):
        """
        Checks if the host is online.

        Parameters
        ----------
        host : str
            Hostname or IP address to ping.

        Returns
        -------
        bool
            True if the host responds to a ping request, False otherwise.
        """
        param = "-n" if platform.system().lower() == "windows" else "-c"
        command = ["ping", param, "1", host]
        return subprocess.call(command) == 0

    def get(self, path, verbose=True, err_count=0, print_response=True):
        """
        Sends a GET request to the TV API.

        Parameters
        ----------
        path : str
            API endpoint path.
        verbose : bool, optional
            Verbose mode flag (default is True).
        err_count : int, optional
            Error count for retries (default is 0).
        print_response : bool, optional
            Flag to print the response (default is True).

        Returns
        -------
        str
            Response text from the API.
        """
        while err_count < int(self.config["DEFAULT"]["num_retries"]):
            if verbose:
                print(
                    "Sending GET request to",
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
            except Exception:
                err_count += 1
                continue
            if verbose:
                print("Request sent!")
            if len(r.text) > 0:
                if print_response:
                    print(r.text)
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

    def post(self, path, body, verbose=True, callback=True, err_count=0):
        """
        Sends a POST request to the TV API.

        Parameters
        ----------
        path : str
            API endpoint path.
        body : str
            Body for the POST request.
        verbose : bool, optional
            Verbose mode flag (default is True).
        callback : bool, optional
            Callback flag (default is True).
        err_count : int, optional
            Error count for retries (default is 0).

        Returns
        -------
        str
            Response text from the API.
        """
        while err_count < int(self.config["DEFAULT"]["num_retries"]):
            if type(body) is str:
                body = json.loads(body)
            if verbose:
                print(
                    "Sending POST request to",
                    str(self.config["TV"]["protocol"]) + str(self.config["TV"]["host"]) + ":" + str(
                        self.config["TV"]["port"]
                    ) + "/" + str(self.config["TV"]["apiv"]) + "/" + str(path)
                    )
            try:
                r = session.post(
                    str(self.config["TV"]["protocol"]) + str(self.config["TV"]["host"]) + ":" + str(
                        self.config["TV"]["port"]
                    ) + "/" + str(path), json=body,
                    verify=False,
                    auth=HTTPDigestAuth(str(self.config["TV"]["user"]), str(self.config["TV"]["pass"])),
                    timeout=2
                    )
            except Exception:
                err_count += 1
                continue
            if verbose:
                print("Request sent!")
            if len(r.text) > 0:
                print(r.text)
                return r.text
            elif r.status_code == 200:
                print(json.dumps({"response": "OK"}))
                return json.dumps({"response": "OK"})
        else:
            if self.config["DEFAULT"]["mqtt_listen"].lower() == "true" and len(sys.argv) == 1:
                self.mqtt_update_status(
                    {
                        "powerstate": "Off", "ambilight": False, "ambihue": False, "ambi_brightness": False,
                        "dls_state": False
                    }
                )
            print(json.dumps({"error": "Can not reach the API"}))
            return json.dumps({"error": "Can not reach the API"})

    def run_command(self, command, body=None, verbose=True, callback=True, print_response=True):
        """
        Runs a command on the TV.

        Parameters
        ----------
        command : str
            Command to run.
        body : str, optional
            Body for the command (default is None).
        verbose : bool, optional
            Verbose mode flag (default is True).
        callback : bool, optional
            Callback flag (default is True).
        print_response : bool, optional
            Flag to print the response (default is True).

        Returns
        -------
        str
            Response text from the API.
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
                    new_body["colorSettings"]["color"]["hue"] = int(body["hue"] * (255 / 360))
                    new_body["colorSettings"]["color"]["saturation"] = int(body["saturation"] * (255 / 100))
                    new_body["colorSettings"]["color"]["brightness"] = int(body["brightness"])
                elif command == "google_assistant":
                    new_body["intent"]["extras"]["query"] = body["query"]
                elif "input_" in command:
                    new_body = self.available_commands["google_assistant"][command]
                    new_body["intent"]["extras"]["query"] = self.available_commands["post"][command]["body"]["query"]
                return self.post(self.available_commands["post"][command]["path"], new_body, verbose, callback)
            else:
                return self.post(self.available_commands["post"][command]["path"], body, verbose, callback)
        elif command in self.available_commands["power"]:
            try:
                return session.post(
                    "http://" + str(self.config["TV"]["host"]) + ":8008/" + self.available_commands["power"][command][
                        "path"], verify=False, timeout=10
                )
            except requests.exceptions.ReadTimeout:
                print("Request timed out. Retrying...")
                return session.post(
                    "http://" + str(self.config["TV"]["host"]) + ":8008/" + self.available_commands["power"][command][
                        "path"], verify=False, timeout=10
                )
        else:
            print("Unknown command")

    def start_mqtt_listener(self):
        """
        Starts the MQTT listener.
        """
        return tools_mqtt.start_mqtt_listener(self)

    def mqtt_update_status(self, update):
        """
        Publishes an update with TV status over MQTT.

        Parameters
        ----------
        update : dict
            Status update to publish.
        """
        return tools_mqtt.mqtt_update_status(self, update)

    def mqtt_update_powerstate(self):
        """
        Updates power state for MQTT status.

        Returns
        -------
        bool
            True if the TV is on, False otherwise.
        """
        return tools_mqtt.mqtt_update_powerstate(self)

    def mqtt_update_ambilight(self):
        """
        Updates ambilight for MQTT status.
        """
        return tools_mqtt.mqtt_update_ambilight(self)

    def mqtt_update_ambihue(self):
        """
        Updates ambihue for MQTT status.
        """
        return tools_mqtt.mqtt_update_ambihue(self)

    def mqtt_update_ambilight_brightness_state(self):
        """
        Updates ambilight brightness for MQTT status.
        """
        return tools_mqtt.mqtt_update_ambilight_brightness_state(self)

    def mqtt_update_display_light_sensor_state(self):
        """
        Updates display light sensor status for MQTT status.
        """
        return tools_mqtt.mqtt_update_display_light_sensor_state(self)

    def start_mqtt_updater(self, verbose=True):
        """
        Runs MQTT update functions with a specified update interval.

        Parameters
        ----------
        verbose : bool, optional
            Verbose mode flag (default is True).
        """
        return tools_mqtt.start_mqtt_updater(self, verbose)


if __name__ == '__main__':
    pylips = Pylips(args.config)
