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

def calculate_distance(csv_path):
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

def resample(csv_path, interval=0.001):
    df = pd.read_csv(csv_path)




output_dir = "data/raw/session_" + constants.SESSION_ID_PREFIX