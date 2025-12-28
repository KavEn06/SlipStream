import socket
import struct
import csv
import os

class datacollector:
    def __init__(self, ip='127.0.0.1', port=5300):
        self.ip = ip 
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.ip, self.port))

        self.current_lap_number = -1
        self.output_file = None
        self.csv_writer = None

        self.format_string = (
            "<iI"    # 8 bytes 
            "4f"     # 16 bytes
            "3f"     # 12 bytes
            "3f"     # 12 bytes
            "3f"     # 12 bytes
            "3f"     # 12 bytes
            "3f"     # 12 bytes
            "4f"     # 16 bytes
            "4f"     # 16 bytes
            "4i"     # 16 bytes
            "4f"     # 16 bytes
            "4f"     # 16 bytes
            "4f"     # 16 bytes
            "4f"     # 16 bytes
            "4f"     # 16 bytes
            "i"      # 4 bytes
            "i"      # 4 bytes
            "i"      # 4 bytes
            "i"      # 4 bytes
            "i"      # 4 bytes
            "3f"     # 12 bytes
            "f"      # 4 bytes
            "f"      # 4 bytes
            "f"      # 4 bytes
            "4f"     # 16 bytes
            "f"      # 4 bytes
            "f"      # 4 bytes
            "f"      # 4 bytes
            "f"      # 4 bytes
            "f"      # 4 bytes
            "f"      # 4 bytes
            "f"      # 4 bytes
            "H"      # 2 bytes
            "B"      # 1 byte
            "B"      # 1 byte
            "B"      # 1 byte
            "B"      # 1 byte
            "B"      # 1 byte
            "B"      # 1 byte
            "b"      # 1 byte
            "b"      # 1 byte
            "b"      # 1 byte
            "4f"     # 16 bytes
            "i"      # 4 bytes
        )

    def process_packet(self, data):
        unpacked_data = struct.unpack(self.format_string, data[:struct.calcsize(self.format_string)])

        telemetry = {
            "IsRaceOn": unpacked_data[0],
            "TimestampMS": unpacked_data[1],
            "EngineMaxRpm": unpacked_data[2],
            "EngineIdleRpm": unpacked_data[3],
            "CurrentEngineRpm": unpacked_data[4],
            "AccelerationX": unpacked_data[5],
            "AccelerationY": unpacked_data[6],
            "AccelerationZ": unpacked_data[7],
            "VelocityX": unpacked_data[8],
            "VelocityY": unpacked_data[9],
            "VelocityZ": unpacked_data[10],
            "AngularVelocityX": unpacked_data[11],
            "AngularVelocityY": unpacked_data[12],
            "AngularVelocityZ": unpacked_data[13],
            "Yaw": unpacked_data[14],
            "Pitch": unpacked_data[15],
            "Roll": unpacked_data[16],
            "NormalizedSuspensionTravelFrontLeft": unpacked_data[17],
            "NormalizedSuspensionTravelFrontRight": unpacked_data[18],
            "NormalizedSuspensionTravelRearLeft": unpacked_data[19],
            "NormalizedSuspensionTravelRearRight": unpacked_data[20],
            "TireSlipRatioFrontLeft": unpacked_data[21],
            "TireSlipRatioFrontRight": unpacked_data[22],
            "TireSlipRatioRearLeft": unpacked_data[23],
            "TireSlipRatioRearRight": unpacked_data[24],
            "WheelRotationSpeedFrontLeft": unpacked_data[25],
            "WheelRotationSpeedFrontRight": unpacked_data[26],
            "WheelRotationSpeedRearLeft": unpacked_data[27],
            "WheelRotationSpeedRearRight": unpacked_data[28],
            "WheelOnRumbleStripFrontLeft": unpacked_data[29],
            "WheelOnRumbleStripFrontRight": unpacked_data[30],
            "WheelOnRumbleStripRearLeft": unpacked_data[31],
            "WheelOnRumbleStripRearRight": unpacked_data[32],
            "WheelInPuddleDepthFrontLeft": unpacked_data[33],
            "WheelInPuddleDepthFrontRight": unpacked_data[34],
            "WheelInPuddleDepthRearLeft": unpacked_data[35],
            "WheelInPuddleDepthRearRight": unpacked_data[36],
            "SurfaceRumbleFrontLeft": unpacked_data[37],
            "SurfaceRumbleFrontRight": unpacked_data[38],
            "SurfaceRumbleRearLeft": unpacked_data[39],
            "SurfaceRumbleRearRight": unpacked_data[40],
            "TireSlipAngleFrontLeft": unpacked_data[41],
            "TireSlipAngleFrontRight": unpacked_data[42],
            "TireSlipAngleRearLeft": unpacked_data[43],
            "TireSlipAngleRearRight": unpacked_data[44],
            "TireCombinedSlipFrontLeft": unpacked_data[45],
            "TireCombinedSlipFrontRight": unpacked_data[46],
            "TireCombinedSlipRearLeft": unpacked_data[47],
            "TireCombinedSlipRearRight": unpacked_data[48],
            "SuspensionTravelMetersFrontLeft": unpacked_data[49],
            "SuspensionTravelMetersFrontRight": unpacked_data[50],
            "SuspensionTravelMetersRearLeft": unpacked_data[51],
            "SuspensionTravelMetersRearRight": unpacked_data[52],
            "CarOrdinal": unpacked_data[53],
            "CarClass": unpacked_data[54],
            "CarPerformanceIndex": unpacked_data[55],
            "DrivetrainType": unpacked_data[56],
            "NumCylinders": unpacked_data[57],
            "PositionX": unpacked_data[58],
            "PositionY": unpacked_data[59],
            "PositionZ": unpacked_data[60],
            "Speed": unpacked_data[61],
            "Power": unpacked_data[62],
            "Torque": unpacked_data[63],
            "TireTempFrontLeft": unpacked_data[64],
            "TireTempFrontRight": unpacked_data[65],
            "TireTempRearLeft": unpacked_data[66],
            "TireTempRearRight": unpacked_data[67],
            "Boost": unpacked_data[68],
            "Fuel": unpacked_data[69],
            "DistanceTraveled": unpacked_data[70],
            "BestLap": unpacked_data[71],
            "LastLap": unpacked_data[72],
            "CurrentLap": unpacked_data[73],
            "CurrentRaceTime": unpacked_data[74],
            "LapNumber": unpacked_data[75],
            "RacePosition": unpacked_data[76],
            "Accel": unpacked_data[77],
            "Brake": unpacked_data[78],
            "Clutch": unpacked_data[79],
            "HandBrake": unpacked_data[80],
            "Gear": unpacked_data[81],
            "Steer": unpacked_data[82],
            "NormalizedDrivingLine": unpacked_data[83],
            "NormalizedAIBrakeDifference": unpacked_data[84],
            "TireWearFrontLeft": unpacked_data[85],
            "TireWearFrontRight": unpacked_data[86],
            "TireWearRearLeft": unpacked_data[87],
            "TireWearRearRight": unpacked_data[88],
            "TrackOrdinal": unpacked_data[89],
        }

        # if racing
        if telemetry["IsRaceOn"] == 0:
            return

        # when new lap 
        if telemetry["LapNumber"] != self.current_lap_number:
            self.start_new_lap_file(telemetry["LapNumber"], list(telemetry.keys()))
        
        # save data 
        if self.csv_writer:
            self.csv_writer.writerow(telemetry.values())

    def start_new_lap_file(self, lap_num, headers):
        if self.output_file:
            self.output_file.close()
            
        self.current_lap_number = lap_num
        
        os.makedirs("data/raw", exist_ok=True)
        
        filename = f"data/raw/lap_{lap_num}.csv"
        print(f"Recording new lap detected: Lap {lap_num}")
        
        self.output_file = open(filename, 'w', newline='')
        self.csv_writer = csv.writer(self.output_file)
        
        self.csv_writer.writerow(headers)

    def run(self):
        print(f"Listening for Forza telemetry on {self.ip}:{self.port}...")
        try:
            while True:
                data, addr = self.sock.recvfrom(1024)
                if len(data) >= 311:
                    self.process_packet(data)
        except KeyboardInterrupt:
            if self.output_file:
                self.output_file.close()
            print("\nStopped logging.")

if __name__ == "__main__":
    logger = datacollector()
    logger.run()