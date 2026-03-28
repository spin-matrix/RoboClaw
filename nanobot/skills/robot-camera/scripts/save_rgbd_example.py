#!/usr/bin/env python3
"""
Simple script to save RGB and Depth images from RealSense camera.
"""
import sys
import os

from teleimager.image_client import ImageClient
import cv2
import numpy as np
from pathlib import Path
import os
def main():
    print('Connecting to image server...')
    client = ImageClient(host='127.0.0.1',request_port=60002, rgbd_request_port=60003, request_bgr=True)
    
    print('Requesting RGBD frame...')
    result = client.get_rgbd_frame(camera='head_camera', timeout=2000)
    
    if result is None:
        print('ERROR: Failed to get RGBD frame')
        print('Make sure the server is running with: python3 -m teleimager.image_server --rs')
        client.close()
        return
    
    rgb_image, depth_image, metadata = result
    
    print(f'RGB shape: {rgb_image.shape}')
    print(f'Depth shape: {depth_image.shape}')
    print(f'Depth scale: {metadata["depth_scale"]}')
    
    SCRIPT_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR= SCRIPT_DIR / "record"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # Save RGB image
    cv2.imwrite(OUTPUT_DIR / 'rgb_frame.png', rgb_image)
    # print('Saved: rgb_frame.png')
    
    # Save depth as colormap for visualization
    depth_colormap = cv2.applyColorMap(
        cv2.convertScaleAbs(depth_image, alpha=0.03),
        cv2.COLORMAP_JET
    )

    cv2.imwrite(OUTPUT_DIR / 'depth_colormap.png', depth_colormap)
    # print('Saved: depth_colormap.png')
    
    # Save raw depth as 16-bit grayscale PNG
    # cv2.imwrite(SCRIPT_ / 'depth_raw.png', depth_image)
    # print('Saved: depth_raw.png (raw uint16 depth data)')
    # import pdb
    # pdb.set_trace()
    # Optional: Save depth as meters (floating point visualization)
    depth_meters = depth_image.astype(np.float32) * metadata['depth_scale']
    # Normalize to 0-255 for visualization (assuming max depth ~5 meters)
    depth_normalized = np.clip(depth_meters / 2 * 255, 0, 255).astype(np.uint8)
    # cv2.imwrite('depth_meters.png', depth_normalized)
    # print('Saved: depth_meters.png (depth in meters, normalized)')
    
    print('\nAll images saved successfully!')
    print(f'  - {str(OUTPUT_DIR / "rgb_frame.png")}: Color image')
    print(f'  - {str(OUTPUT_DIR / "depth_colormap.png")}: Depth visualization (JET colormap)')
    #print('  - depth_raw.png: Raw 16-bit depth data')
    #print('  - depth_meters.png: Depth in meters (normalized)')
    
    client.close()

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
