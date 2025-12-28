import socket
import struct

# To check if the byte size received matches expected size
def receive_forza_byte_size(ip='127.0.0.1', port=5300):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))
    
    while True:
        data, addr = sock.recvfrom(1024)  # Adjust buffer size if needed
        print(f"Received data length: {len(data)} bytes")

        # Compare with expected length (332 bytes in this case)
        if len(data) == 332:
            unpacked_data = struct.unpack(format_string, data)
            # Handle unpacked data
        else:
            print(f"Unexpected data length: {len(data)}. Expected 332 bytes.")

#Recieve and unpack Forza telemetry data
def receive_forza_telemetry(ip='127.0.0.1', port=5300):
    # Create a UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Bind the socket to the specified IP and port
    sock.bind((ip, port))
    
    print(f"Listening for Forza telemetry data on {ip}:{port}...")

    # Infinite loop to continuously receive telemetry data
    while True:
        # Receive the data from Forza
        data, address = sock.recvfrom(1024)  # Buffer size of 1024 bytes
        
        format_string = (
            "<iI"    # 8 bytes (explicit packing, no alignment)
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
        
        # total_size = struct.calcsize(format_string)
        # print(f"Total calculated size with explicit packing: {total_size} bytes")
        # print(f"Received data length: {len(data)} bytes")
        # Unpack the data based on the defined structure
        unpacked_data = struct.unpack(format_string, data)
        
        # Map the unpacked data to meaningful names
        telemetry_data = {
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

        # Print the telemetry data for testing purposes
        print(telemetry_data["CurrentEngineRpm"])
        print("\033[H\033[2J")




# Call the function to start listening for telemetry data
receive_forza_telemetry()