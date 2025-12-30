import pandas as pd
import numpy as np

def calculate_distance(csv_path):
    df = pd.read_csv(csv_path)

    positions = ['PostionX', 'PositionY', 'PositionZ']

    distance = [0.0] 

    for i in range(1, len(df)):
        x0, y0, z0 = df.loc[i-1, positions]
        x1, y1, z1 = df.loc[i, positions]

        step_distance = np.sqrt((x1 - x0)**2 + (y1 - y0)**2 + (z1 - z0)**2)
        distance.append(distance[i-1] + step_distance)

    df['Distance'] = distance
    df.to_csv(csv_path, index=False)


