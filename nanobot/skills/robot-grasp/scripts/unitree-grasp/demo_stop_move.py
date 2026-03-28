from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
    

if __name__ == "__main__":
    ChannelFactoryInitialize(0, "eth0")
    sport_client = LocoClient()  
    sport_client.SetTimeout(3.0)
    sport_client.Init()
    sport_client.SetVelocity(0, 0, 0, 1)
