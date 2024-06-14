import json
import socket
import influxdb_client
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Read values from .env file
INFLUXDB_HOST = os.getenv('INFLUXDB_HOST')
INFLUXDB_PORT = int(os.getenv('INFLUXDB_PORT'))
INFLUXDB_TOKEN = os.getenv('INFLUXDB_TOKEN')
INFLUXDB_ORGANIZATION = os.getenv('INFLUXDB_ORGANIZATION')
INFLUXDB_BUCKET = os.getenv('INFLUXDB_BUCKET')
SHELLY_PORT = int(os.getenv('SHELLY_PORT'))


class ShellyResponse:
    def __init__(self, response_type: str = "Failure", source: str = "", temperature: float = 0.0,
                 humidity_level: float = 0.0, power_consumption: float = 0.0) -> object:
        self.type: str = response_type
        self.src: str = source
        self.temp: float = temperature
        self.humidity: float = humidity_level
        self.power: float = power_consumption


# Function to parse Shelly's RPC response
def parse_shelly_response(data) -> ShellyResponse:

    try:
        data = data.decode('utf-8')
        response = json.loads(data)
        if (response['method'] == "NotifyStatus"):
            print(f"got status: {response}")

            if 'shellyplusplugs' in response.get('src'):
                power = response.get('params').get('switch:0').get('apower')
                if power is None:
                    return ShellyResponse()

                return ShellyResponse('power', response['src'], 0.0, 0.0, power)

            return ShellyResponse()
        elif response['method'] == 'NotifyEvent':
            return ShellyResponse()

        resp = response.get('params', {}).get('temperature:0')
        temp = resp["tC"]
        resp2 = response.get('params', {}).get('humidity:0')
        hum = resp2["rh"]
        return ShellyResponse('environment', response['src'], temp, hum, 0)
    except Exception as e:
        # print(f"Error parsing Shelly response: {e}")
        return ShellyResponse()


# InfluxDB client setup
client = influxdb_client.InfluxDBClient(
    url=f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}",
    token=INFLUXDB_TOKEN,
    organization=INFLUXDB_ORGANIZATION
)

# UDP socket setup
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", SHELLY_PORT))

while True:
    try:
        data, address = sock.recvfrom(1024)
        Measurement: ShellyResponse = parse_shelly_response(data)

        if Measurement.type == 'Failure':
            pass

        elif Measurement.type == 'environment':
            if Measurement.temp is not None:
                # Write temperature to InfluxDB
                # Write temperature to InfluxDB
                point_temp = influxdb_client.Point("shelly_h_t").tag("sensor", Measurement.src).field("temperature",
                                                                                                      Measurement.temp)
                point_hum = influxdb_client.Point("shelly_h_t").tag("sensor", Measurement.src).field("humidity",
                                                                                                     Measurement.humidity)
                write_api = client.write_api()
                write_api.write(org=INFLUXDB_ORGANIZATION, bucket=INFLUXDB_BUCKET, record=[point_temp, point_hum])

                print(f"Received temperature: {Measurement.temp}°C and {Measurement.humidity}%rh")

        elif Measurement.type == 'power':
            point_power = influxdb_client.Point("shelly_h_t").tag("sensor", Measurement.src).field("power",
                                                                                                   Measurement.power)
            write_api = client.write_api()
            
            write_api.write(org=INFLUXDB_ORGANIZATION, bucket=INFLUXDB_BUCKET, record=point_power)

            print(f'Received Power from {Measurement.src} of {Measurement.power}W')

    except Exception as e:
        print(e)
