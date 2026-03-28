from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
import argparse

def parse_arg():
    parser = argparse.ArgumentParser(description="use sdk to control moving")
    parser.add_argument(
        'distance',
        type=float,
        help='move distance'
    )
    args = parser.parse_args()
    return args

if __name__ == "__main__":
    ChannelFactoryInitialize(0, "eth0")
    sport_client = LocoClient()  
    sport_client.SetTimeout(3.0)
    sport_client.Init()

    args = parse_arg()
    speed = 0.3
    duration = args.distance / speed
    sport_client.SetVelocity(speed, 0, 0, duration)
    time.sleep(duration+1) # wait for the movement to complete
