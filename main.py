import os
from dataclasses import dataclass
import socket
from enum import StrEnum
import logging
import json

from dotenv import load_dotenv
import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS

# setup a basicLoger
logging.basicConfig(level=logging.INFO)
log = logging.getLogger()

# Load environment variables from .env file
load_dotenv()

# Read values from .env file
INFLUXDB_HOST = os.getenv('INFLUXDB_HOST')
INFLUXDB_PORT = int(os.getenv('INFLUXDB_PORT'))
INFLUXDB_TOKEN = os.getenv('INFLUXDB_TOKEN')
INFLUXDB_ORGANIZATION = os.getenv('INFLUXDB_ORGANIZATION')
INFLUXDB_BUCKET = os.getenv('INFLUXDB_BUCKET')
SHELLY_PORT = int(os.getenv('SHELLY_PORT'))

# InfluxDB client setup
client = influxdb_client.InfluxDBClient(
    url=f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}",
    token=INFLUXDB_TOKEN,
    org=INFLUXDB_ORGANIZATION
)

# UDP socket setup
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', SHELLY_PORT))


class ResponseType(StrEnum):
    FAILURE = "failure"
    POWER = "power"
    ENVIRONMENT = "environment"


@dataclass(slots=True)
class ShellyResponse:
    response_type: str = ResponseType.FAILURE
    source: str = ""
    temperature: float = 0.0
    humidity_level: float = 0.0
    power_consumption: float = 0.0

    def __str__(self) -> str:
        return (f"response_type: {str(self.response_type)}" +
                f"\nsource: {self.source}" +
                f"\ntemperature: {self.temperature}°C" +
                f"\nhumidity_level: {self.humidity_level}%rh" +
                f"\npower_consumption: {self.power_consumption}W")


# Function to parse Shelly's RPC response
def parse_shelly_response(data) -> ShellyResponse:
    try:
        data = data.decode('utf-8')
        response = json.loads(data)
        match response["method"]:
            case "NotifyStatus":
                log.debug(f"got status: {response}")

                if 'shellyplusplugs' in response.get('src'):
                    power = response.get('params', {}).get('switch:0', {}).get('apower')
                    if power is not None:
                        return ShellyResponse(ResponseType.POWER, response['src'], power_consumption=power)

                return ShellyResponse()

            case "NotifyEvent":
                return ShellyResponse()

        resp = response.get('params', {})
        temp = resp.get('temprature:0', {}).get("tC")
        humid = resp.get('humidity:0', {}).get("rh")

        if temp is not None and humid is not None:
            return ShellyResponse(ResponseType.ENVIRONMENT, response['src'], temp, humid, power_consumption=0.0)

        return ShellyResponse()

    except Exception as e:
        # log.exception(f"Error parsing Shelly response: {e}")
        return ShellyResponse()


def process_response() -> None:
    try:
        data, address = sock.recvfrom(1024)
        measurement: ShellyResponse = parse_shelly_response(data)

        match measurement.response_type:
            case ResponseType.FAILURE:
                pass

            case ResponseType.ENVIRONMENT:
                if measurement.temperature is not None:
                    # Write temperature to InfluxDB
                    # Write temperature to InfluxDB
                    point = influxdb_client.Point("shelly_h_t").tag("sensor", measurement.source)
                    point_temp = point.field("temperature", measurement.temperature)
                    point_humid = point.field("humidity", measurement.humidity_level)
                    with client.write_api(write_options=SYNCHRONOUS) as writer:
                        writer.write(bucket=INFLUXDB_BUCKET, record=[point_temp, point_humid])

                    log.info(f"Received temperature: {measurement.temperature}°C and {measurement.humidity_level}%rh")

            case ResponseType.POWER:
                point = influxdb_client.Point("shelly_h_t").tag("sensor", measurement.source)
                point_power = point.field("power", measurement.power_consumption)

                with client.write_api(write_options=SYNCHRONOUS) as writer:
                    writer.write(org=INFLUXDB_ORGANIZATION,
                                 bucket=INFLUXDB_BUCKET,
                                 record=point_power,
                                 )

                log.info(f'Received Power from {measurement.source} of {measurement.power_consumption}W')

    except Exception as e:
        log.exception(e)


def main() -> None:
    while True:
        process_response()


if __name__ == "__main__":
    main()
