# Unitree Grasp

## Installation

### 1. Prepare Environment
```bash
git clone --recursive https://github.com/alter-c/unitree-grasp.git
```
```bash
conda create -n grasp python=3.8 casadi=3.6.5 pinocchio=3.2.0 -c conda-forge
conda activate grasp

cd third_party/unitree_sdk2_python
pip3 install -e .

cd ../..
pip3 install -r requirements.txt
```
### 2. Torch Package
[PyTorch for Jetson](https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048)
```bash
pip3 uninstall torch torchvision

# PyTorch for Jetson (https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048)
pip3 install torch-2.1.0a0+41361538.nv23.06-cp38-cp38-linux_aarch64.whl

# Torchvision 
sudo apt-get install libjpeg-dev zlib1g-dev libpython3-dev libopenblas-dev libavcodec-dev libavformat-dev libswscale-dev
git clone --branch v0.16.1 https://github.com/pytorch/vision torchvision
cd torchvision
export BUILD_VERSION=0.16.1  
python3 setup.py install --user
cd ../ # for test
```

## Usage

### Quick Start

#### Web api
In the terminal and execute:
```bash
python demo_api.py
```
Then open a new terminal and you can execute below commands:
```bash
curl '0.0.0.0:8080/api/unitree/grasp?target=bottle' # grasp bottle

curl '0.0.0.0:8080/api/unitree/regrasp?target=bottle' 

curl '0.0.0.0:8080/api/unitree/retract' 

curl '0.0.0.0:8080/api/unitree/handover' # handover object

curl '0.0.0.0:8080/api/unitree/stop' # stop current action and release arm to walk

curl '0.0.0.0:8080/api/unitree/stop_move' # stop walk
```
其中，可识别的物品为coco数据集中物品，可抓取或者关注的物品类别参考yolo_detector.py中interested_classes = ["bottle", "orange", "apple", "person"]

- 抓取动作(grasp)会执行至抓住物品
- 然后执行收回动作(retract)，机器人会逐步收回手臂并放下，但不会松开手
- 等待机器人远离桌面后，可执行递出(handover)动作，会走向人并递出放下手中物品
- stop命令用于放松手臂及灵巧手
- stop_move命令用于直接停止机器人移动

### 文件目录及功能说明
- control/ 机器人控制相关sdk封装
- models/ yolo模型文件
- assets/ 机器人urdf文件
- third_party/ 宇树sdk
- tools/ 定义坐标转换等工具

#### 示例调用脚本
- demo.py 程序完整测试流程脚本
- demo_api.py 将各动作封装为服务，通过api方式调用

#### 视觉与动作模块
- yolo_detector.py 视觉获取与检测模块，主要关注get_interested_detection()方法，会启动两个进程用于获取与识别图像，visualize=True可启动可视化进程
- action_executor.py 动作执行模块，封装相关动作，如抓取、递出、移动

#### 单独动作脚本（用于其他模块直接以脚本形式调用）
- demo_grasp.py bottle(参数为抓取类别)
    - 抓取流程：识别物品 -> 根据坐标差移动 -> 再次识别 -> 执行抓取动作（具体抓取流程见脚本内容）
- demo_retract.py right(参数为收回左手或右手)
- demo_handover.py right(同理)
- demo_stop_move.py (无参数，直接调用即可停止)

print(f"[Unitree] Grasp success: Use left hand") 最终会打印输出该类信息，动作是否执行成功；如果抓取成功，会打印抓取对应的手


### Test

#### Test whole demo pipeline
```bash
python demo.py
```

#### Test image process
```bash
python yolo_detector.py
```

#### Test action
```bash
python action_executor.py
```


## FAQ
+ cyclonedds bug：[FAQ](https://github.com/unitreerobotics/unitree_sdk2_python?tab=readme-ov-file#faq)



