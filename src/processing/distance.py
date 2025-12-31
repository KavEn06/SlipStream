import pandas as pd
import numpy as np
import constants

""" def calculate_distance(csv_path):
    df = pd.read_csv(csv_path)

    positions = ['PostionX', 'PositionY', 'PositionZ']

    distance = [0.0] 

    for i in range(1, len(df)):
        x0, y0, z0 = df.loc[i-1, positions]
        x1, y1, z1 = df.loc[i, positions]

        step_distance = np.sqrt((x1 - x0)**2 + (y1 - y0)**2 + (z1 - z0)**2)
        distance.append(distance[i-1] + step_distance)

    df['Distance'] = distance
    df.to_csv(csv_path, index=False) """

def calculate_distance(lap_name):
    csv_path = "data/raw/session_" + constants.SESSION_ID_PREFIX + "/" + lap_name
    df = pd.read_csv(csv_path)

    positions_columns = ['PostionX', 'PositionY', 'PositionZ']

    for col in positions_columns:
        if col not in df.columns:
            raise ValueError(f"Missing {col}")
        
    dx = df['PostionX'] - df['PostionX'].shift(1)
    dy = df['PositionY'] - df['PositionY'].shift(1)
    dz = df['PositionZ'] - df['PositionZ'].shift(1)

    df['StepDistance'] = np.sqrt(dx**2 + dy**2 + dz**2)  
    df['StepDistance'].fillna(0.0, inplace=True)

    df['Distance'] = df['StepDistance'].cumsum()
    df.drop(columns=['StepDistance'], inplace=True)

    df['DistanceNorm'] = df['Distance'] / df['Distance'].iloc[-1]

    df.to_csv(csv_path, index=False)

def resample(lap_name, interval=0.001):
    csv_path = "data/raw/session_" + constants.SESSION_ID_PREFIX + "/" + lap_name
    df = pd.read_csv(csv_path)

    processed_filepath = "data/processed/session_" + constants.SESSION_ID_PREFIX + "/" + lap_name
    resampled_df = pd.DataFrame()

    #distancenorm is intervals and actual distance will be laplength times distancenorm
    resample_signals = ['CurrentEngineRpm', 'Speed', 'Power', 'Torque', 'Boost', 'Accel', 'Brake', 'Steer']

    intervals = np.linspace(0, 1, int(1/interval))

    resampled_df['DistanceNorm'] = intervals
    resampled_df['Distance'] = intervals * df['Distance'].iloc[-1]

    for signal in resample_signals:
        resampled_df[signal] = np.interp(intervals, df['DistanceNorm'], df[signal])
    
    resampled_df.to_csv(processed_filepath, index=False)




output_dir = "data/raw/session_" + constants.SESSION_ID_PREFIX