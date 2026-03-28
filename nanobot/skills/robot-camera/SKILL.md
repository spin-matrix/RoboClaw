---
name: robot-camera
description: get the robot's live rgb and depth images and answer what the robot currently sees. use this skill when the user asks what the robot sees now, asks to view the robot camera, or asks to fetch the latest rgb or depth image.（获取机器人的实时彩色图像和深度图像，并说明机器人当前看到的内容。当用户询问机器人现在看到什么、要求查看机器人摄像头、或要求获取最新的彩色图像或深度图像时，可使用该技能。）
metadata:
  nanobot:
    title: Robot Camera
    icon: camera
---

Run `cd {baseDir}/scripts && uv run {baseDir}/scripts/save_rgbd_example.py` first to capture the latest robot-view RGB and depth images.

Use this skill when the user asks things like:
- What do you see
- What does the robot see now
- Get the robot's real-time image
- View the robot's perspective
- Get the current RGB / depth map

After capture:
- The saved image is located at `{baseDir}/scripts/record/rgb_frame.png`, inspect the newest RGB image first
- The depth color map is located at `{baseDir}/scripts/record/depth_colormap.png`, use depth only for distance or obstacle hints
- feed the image to image understanding tool if you don't have visual understanding ability, otherwise directly feed the image to your context then answer user's questions based on above, not from guesswork

If capture fails, say the live robot image could not be retrieved and do not make up what the robot sees.

---
name: robot-camera
description: 获取机器人的实时彩色图像和深度图像，并说明机器人当前看到的内容。当用户询问机器人现在看到什么、要求查看机器人摄像头、或要求获取最新的彩色图像或深度图像时，可使用该技能。
metadata:
  nanobot:
    title: Robot Camera
    icon: camera
---

首先运行命令 `cd {baseDir}/scripts && uv run {baseDir}/scripts/save_rgbd_example.py`，以捕获最新的机器人视角彩色图像和深度图像。

当用户提出以下问题时，可使用该技能：
- 你看到了什么
- 机器人现在看到了什么
- 获取机器人的实时图像
- 查看机器人的视角
- 获取当前的彩色图像/深度图

捕获图像后：
- RGB图像路径为`{baseDir}/scripts/record/rgb_frame.png`, 首先查看最新的RGB图像
- 保存的深度图像路径为`{baseDir}/scripts/record/depth_colormap.png`，深度图像仅用于距离或障碍物提示
- 若自身不具备视觉理解能力，可将图像输入至图像理解工具；若具备视觉理解能力，则直接将图像输入至上下文，再基于上述信息回答用户问题，不得凭空猜测

若捕获图像失败，需说明无法获取机器人的实时图像，且不得编造机器人看到的内容。
