import numpy as np

def get_default_extrinsics():
    theta = np.radians(-48)
    c, s = np.cos(theta), np.sin(theta)

    M_align = np.array([
        [0, 0, 1, 0],
        [-1, 0, 0, 0],
        [0, -1, 0, 0],
        [0, 0, 0, 1]
    ]) # align camera to robot frame

    M_pitch = np.array([
        [1, 0, 0, 0],
        [0, c, -s, 0],
        [0, s, c, 0],
        [0, 0, 0, 1]
    ]) # camear rotation

    M_trans = np.array([
        [1, 0, 0, 0.04765],
        [0, 1, 0, 0],
        [0, 0, 1, 0.46268],
        [0, 0, 0, 1]
    ]) # camera translation

    default_extr = M_trans @ M_align @ M_pitch
    return default_extr 

def get_realsense_intrinsics(rs_profile):
    import pyrealsense2 as rs
    rs_intr = rs_profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
    intr = np.array([
        [rs_intr.fx, 0, rs_intr.ppx],
        [0, rs_intr.fy, rs_intr.ppy],
        [0, 0, 1]
    ])
    return intr

class CoordinateTransformer:
    def __init__(self, intr, extr):
        self.intr = intr # realsense or image_server
        self.extr = extr # robot

        self.intr_inv = np.linalg.inv(self.intr)
    
    def pixel_to_camera(self, pixel_coords, depth):
        u, v = pixel_coords
        home_pixel_coords = np.array([u, v, 1])
        # x_c = (u - self.intr.ppx) * depth / self.intr.fx
        # y_c = (v - self.intr.ppy) * depth / self.intr.fy
        # z_c = depth
        camera_coords = self.intr_inv @ home_pixel_coords * depth
        return camera_coords

    def camera_to_world(self, camera_coords):
        R, t = self.extr[:3, :3], self.extr[:3, 3]
        world_coords = R @ camera_coords + t
        return world_coords

    def pixel_to_world(self, pixel_coords, depth):
        camera_coords = self.pixel_to_camera(pixel_coords, depth)
        world_coords = self.camera_to_world(camera_coords)
        return world_coords

if __name__ == "__main__":
    default_extr = get_default_extrinsics()
    print(f"Default Extrinsic Matrix:\n{default_extr}")
        