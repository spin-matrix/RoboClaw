# Copyright 2025 YuShu TECHNOLOGY CO.,LTD ("Unitree Robotics")
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# ------------------------------------------------------------------------------
# NOTICE: This file is modified by Unitree Robotics based on portions of
# the "beavr-bot" project (https://github.com/ARCLab-MIT/beavr-bot),
# which is licensed under the MIT License.
# ------------------------------------------------------------------------------

import cv2
import time
import contextlib
import queue
import threading
from typing import Any, Dict, Optional, Tuple
import zmq
import numpy as np
import yaml
import os
from collections import deque
import logging_mp
logger_mp = logging_mp.getLogger(__name__)
logger_mp.setLevel(logging_mp.INFO)

# ========================================================
# Utility tools
# ========================================================
class TripleRingBuffer:
    def __init__(self):
        self.buffer = [None, None, None]
        self.write_index = 0            # Index where the next write will occur
        self.latest_index = -1          # Index of the latest written data
        self.read_index = -1            # Index of the current read data
        self.lock = threading.Lock()

    def write(self, data):
        with self.lock:
            self.buffer[self.write_index] = data
            self.latest_index = self.write_index
            self.write_index = (self.write_index + 1) % 3
            if self.write_index == self.read_index:
                self.write_index = (self.write_index + 1) % 3

    def read(self):
        with self.lock:
            if self.latest_index == -1:
                return None  # No data has been written yet
            self.read_index = self.latest_index
        return self.buffer[self.read_index]

class SimpleFPSMonitor:
    def __init__(self, window_size: int):
        self._times = deque(maxlen=window_size)
        self._last_tick = None
        self._fps = 0.0

    def tick(self):
        now = time.perf_counter_ns()

        if self._last_tick is not None:
            interval_ns = now - self._last_tick
            if interval_ns < 100_000:
                return

            self._times.append(interval_ns)
            if len(self._times) == self._times.maxlen:
                rolling_sum = sum(self._times)
                if rolling_sum > 0:
                    self._fps = (len(self._times) * 1_000_000_000.0) / rolling_sum
            else:
                self._fps = 0.0

        self._last_tick = now

    def reset(self):
        self._times.clear()
        self._last_tick = None
        self._fps = 0.0

    @property
    def fps(self) -> float:
        """Return 0.0 until the sampling window is fully populated."""
        return self._fps
# ========================================================
# ZMQ publish
# ========================================================
class ZMQ_PublisherThread(threading.Thread):
    """Thread that owns a PUB socket and handles publishing via a queue."""

    def __init__(self, port: int, host: str = "0.0.0.0", context: Optional[zmq.Context] = None):
        """Initialize publisher thread.

        Args:
            port: The port number to bind to.
            host: The host address to bind to (default: all interfaces "*").
        """
        super().__init__(daemon=True)
        self._port = port
        self._host = host
        self._context = context
        self._socket = None
        self._running = True
        self._queue = queue.Queue(maxsize=10)  # Limit queue size to prevent memory issues
        self._started = threading.Event()

    def send(self, data: Any) -> None:
        """Send data to the publisher queue (thread-safe).

        Args:
            data: The data to publish
        """
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f"PublisherThread expects bytes, got {type(data)}")

        try:
            self._queue.put_nowait(data)
        except queue.Full:
            logger_mp.warning(f"Publisher queue full for {self._host}:{self._port}, dropping message")
        except Exception as e:
            logger_mp.error(f"Error serializing data for publisher: {e}")

    def stop(self) -> None:
        """Stop the publisher thread gracefully."""
        self._running = False
        # Put a sentinel value(None) to unblock the queue if needed
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(None)
        self.join(timeout=1)
        if self.is_alive():
            logger_mp.warning("Publisher thread did not stop gracefully")

    def run(self) -> None:
        """Main publisher loop with socket creation in worker thread."""
        try:
            # Create socket in the worker thread
            self._socket = self._context.socket(zmq.PUB)
            self._socket.setsockopt(zmq.SNDHWM, 1)  # Only keep latest message
            self._socket.setsockopt(zmq.LINGER, 0)
            self._socket.bind(f"tcp://{self._host}:{self._port}")

            # Signal that socket is ready
            self._started.set()
            while self._running:
                try:
                    # Get data from queue with timeout to allow checking _running
                    data = self._queue.get(timeout=0.1)

                    # Check for sentinel value
                    if data is None:
                        break

                    try:
                        self._socket.send(data, zmq.NOBLOCK)
                    except zmq.Again:
                        logger_mp.warning(f"High water mark reached for at {self._host}:{self._port}, dropping message")
                    except zmq.ZMQError as e:
                        logger_mp.error(f"Failed to publish to at {self._host}:{self._port}: {e}")
                        break

                except queue.Empty:
                    # Queue was empty, just continue
                    continue
                except Exception as e:
                    if self._running:
                        logger_mp.error(f"Error in publisher loop: {e}")
                    break

        except Exception as e:
            logger_mp.error(f"Failed to initialize publisher socket: {e}")
        finally:
            # Ensure socket is closed when thread exits
            if self._socket:
                try:
                    self._socket.close()
                except Exception as e:
                    logger_mp.warning(f"Error closing socket in cleanup: {e}")
                self._socket = None

    def wait_for_start(self, timeout: float = 1.0) -> bool:
        """Wait until socket context is ready"""
        return self._started.wait(timeout=timeout)

class ZMQ_PublisherManager:
    """Centralized management of ZMQ publishers"""

    _instance: Optional["ZMQ_PublisherManager"] = None
    _publisher_threads: Dict[Tuple[str, int], ZMQ_PublisherThread] = {}
    _lock = threading.Lock()
    _running = True

    def __init__(self):
        self._context = zmq.Context()

    def _create_publisher_thread(self, port: int, host: str = "0.0.0.0") -> ZMQ_PublisherThread:
        try:
            publisher_thread = ZMQ_PublisherThread(port, host, self._context)
            publisher_thread.start()
            # Wait for the thread to start and socket to be ready
            if not publisher_thread.wait_for_start(timeout=5.0):  # Increase timeout to 5 seconds
                raise ConnectionError(f"Publisher thread failed to start for {host}:{port}")

            return publisher_thread
        except Exception as e:
            logger_mp.error(f"Failed to create publisher thread for {host}:{port}: {e}")
            raise

    def _get_publisher_thread(self, port: int, host: str = "0.0.0.0") -> ZMQ_PublisherThread:
        key = (host, port)
        with self._lock:
            if key not in self._publisher_threads:
                self._publisher_threads[key] = self._create_publisher_thread(port, host)
            return self._publisher_threads[key]

    def _close_publisher(self, key: Tuple[str, int]) -> None:
        with self._lock:
            if key in self._publisher_threads:
                try:
                    self._publisher_threads[key].stop()
                except Exception as e:
                    logger_mp.error(f"Error stopping publisher at {key[0]}:{key[1]}: {e}")
                del self._publisher_threads[key]

    # --------------------------------------------------------
    # public api
    # --------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "ZMQ_PublisherManager":
        """Get or create the singleton instance with thread safety.
        Returns:
            The singleton ZMQPublisherManager instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def publish(self, data: Any, port: int, host: str = "0.0.0.0") -> None:
        """Publish data to queue-based communication.

        Args:
            data: The data to publish
            port: The port number
            host: The host address

        Raises:
            ConnectionError: If publishing fails
            SerializationError: If data serialization fails
        """
        if not self._running:
            raise RuntimeError("ZMQPublisherManager is closed")

        try:
            publisher_thread = self._get_publisher_thread(port, host)
            publisher_thread.send(data)
        except Exception as e:
            logger_mp.error(f"Unexpected error in publish: {e}")
            raise

    def close(self) -> None:
        """Close all publishers."""
        self._running = False
        # close all publishers
        with self._lock:
            for key, publisher_thread in list(self._publisher_threads.items()):
                try:
                    publisher_thread.stop()
                except Exception as e:
                    logger_mp.error(f"Error stopping publisher at {key[0]}:{key[1]}: {e}")
            self._publisher_threads.clear()

# ========================================================
# ZMQ subscribe
# ========================================================
class TeleImage:
    _NOT_SET = object()
    __slots__ = ['jpg', '_bgr', 'fps']

    def __init__(self, fps: float, jpg: Optional[bytes], bgr: Any = _NOT_SET):
        self.fps = fps
        self.jpg = jpg
        self._bgr = bgr

    @property
    def bgr(self) -> Optional[np.ndarray]:
        """ Get decoded BGR image if decoding is enabled and data is available."""
        # state 1: decoding disabled
        if self._bgr is TeleImage._NOT_SET:
            logger_mp.warning(f"[TeleImager] Accessing .bgr but decoding was DISABLED.")
            return None
        # state 2: decoding enabled but no data
        if self._bgr is None:
            logger_mp.debug(f"[TeleImager] Accessing .bgr but no image data received.")
            return None
        # state 3: decoding enabled and data available
        return self._bgr

    def __bool__(self):
        """ Truth value based on whether jpg byte data is available """
        return bool(self.jpg)

    def __iter__(self):
        """ Allow unpacking like: jpg, bgr, fps = teleimage_instance """
        yield self.fps
        yield self.jpg
        yield (None if self._bgr is TeleImage._NOT_SET else self._bgr)

    def __repr__(self):
        """ String representation for debugging """
        size = len(self.jpg) if self.jpg else 0
        state = "DISABLED" if self._bgr is TeleImage._NOT_SET else ("FAILED" if self._bgr is None else "OK")
        return f"TeleImage(fps={self.fps:.1f}, jpg_byte_size={size}, bgr_state={state})"


class ZMQ_SubscriberThread(threading.Thread):
    """Thread that owns a SUB socket and handles receiving the latest message."""

    def __init__(self, host: str, port: int, context: Optional[zmq.Context] = None, request_bgr: bool = False):
        """Initialize subscriber thread.

        Args:
            port: The port number to connect to.
            host: The server host address to connect to.
            context: Optional ZMQ context to use. If None, a new context will be created.
        """
        super().__init__(daemon=True)
        self._host = host
        self._port = port
        self._context = context or zmq.Context.instance()
        self._request_bgr = request_bgr

        self._socket = None
        self._running = True
        self._started = threading.Event()

        self._jpg_3ring_buffer = TripleRingBuffer()
        self._fps_monitor = SimpleFPSMonitor(window_size=10)
        if self._request_bgr:
            self._bgr_3ring_buffer = TripleRingBuffer()
            self._bgr_decode_queue = queue.Queue(maxsize=1)
            self._decoder_thread = threading.Thread(target=self._decoder_loop, daemon=True)
            self._decoder_thread.start()
        else:
            self._bgr_3ring_buffer = None
            self._bgr_decode_queue = None
            self._decoder_thread = None

    def _decode_image(self, jpg_bytes):
        """Decode JPEG bytes to OpenCV image."""
        if jpg_bytes is None:
            return None
        try:
            np_img = np.frombuffer(jpg_bytes, dtype=np.uint8)
            return cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        except Exception as e:
            logger_mp.warning(f"[ZMQ_SubscriberThread] Failed to decode image: {e}")
            return None

    def _decoder_loop(self):
        while self._running:
            try:
                jpg_bytes = self._bgr_decode_queue.get(timeout=0.1)
                if jpg_bytes is None:
                    continue
                img_numpy = self._decode_image(jpg_bytes)
                self._bgr_3ring_buffer.write(img_numpy)
                self._bgr_decode_queue.task_done()
            except queue.Empty:
                continue

    def _wait_for_start(self, timeout: float = 1.0) -> bool:
        """Wait until socket context is ready"""
        return self._started.wait(timeout=timeout)

    # --------------------------------------------------------
    # public api
    # --------------------------------------------------------
    def recv(self) -> TeleImage:
        """Get the latest received message.

        Returns:
            The latest message as a TeleImage object containing raw bytes, decoded BGR image (if enabled), and FPS.
        """
        current_fps = self._fps_monitor.fps
        jpg_data = self._jpg_3ring_buffer.read()
        if not self._request_bgr:
            return TeleImage(fps=current_fps, jpg=jpg_data)

        bgr_data = self._bgr_3ring_buffer.read()
        return TeleImage(fps=current_fps, jpg=jpg_data, bgr=bgr_data)

    def stop(self) -> None:
        """Stop the subscriber thread gracefully."""
        self._running = False
        self.join(timeout=1.0)
        if self.is_alive():
            logger_mp.warning("Subscriber thread did not stop gracefully")

    def run(self) -> None:
        """Main subscriber loop with socket creation in worker thread."""
        try:
            # Create socket in the worker thread
            self._socket = self._context.socket(zmq.SUB)
            self._socket.setsockopt(zmq.RCVHWM, 1)  # Only keep latest message
            self._socket.setsockopt(zmq.LINGER, 0)
            self._socket.connect(f"tcp://{self._host}:{self._port}")
            self._socket.setsockopt_string(zmq.SUBSCRIBE, "")

            poller = zmq.Poller()
            poller.register(self._socket, zmq.POLLIN)

            # Signal that socket is ready
            self._started.set()
            while self._running:
                events = dict(poller.poll(timeout=100))
                if self._socket in events:
                    try:
                        # receive the latest message
                        img_bytes = self._socket.recv()
                        # write to 3-ring-buffer
                        self._jpg_3ring_buffer.write(img_bytes)
                        # enqueue for decoding if needed
                        if self._request_bgr:
                            try:
                                if self._bgr_decode_queue.full():
                                    self._bgr_decode_queue.get_nowait()
                                self._bgr_decode_queue.put_nowait(img_bytes)
                            except queue.Full:
                                pass
                        # update fps
                        self._fps_monitor.tick()

                    except Exception as e:
                        if self._running:
                            logger_mp.error(f"Error in subscriber loop: {e}")
                        break
                else:
                    self._jpg_3ring_buffer.write(None)
                    if self._request_bgr:
                        try:
                            if self._bgr_decode_queue.full():
                                self._bgr_decode_queue.get_nowait()
                            self._bgr_decode_queue.put_nowait(None)
                        except queue.Full:
                            pass

                    self._fps_monitor.reset()
                    logger_mp.debug(f"No message received from {self._host}:{self._port} within timeout.")
        except Exception as e:
            logger_mp.error(f"Failed to initialize subscriber socket: {e}")
        finally:
            # Ensure socket is closed when thread exits
            if self._socket:
                try:
                    self._socket.close()
                except Exception as e:
                    logger_mp.warning(f"Error closing socket in cleanup: {e}")
                self._socket = None

class ZMQ_SubscriberManager:
    """Centralized management of ZMQ subscribers."""

    _instance: Optional["ZMQ_SubscriberManager"] = None
    _subscriber_threads: Dict[Tuple[str, int], ZMQ_SubscriberThread] = {}
    _lock = threading.Lock()
    _running = True

    def __init__(self):
        self._context = zmq.Context()

    def _create_subscriber_thread(self, host: str, port: int, request_bgr: bool = False) -> ZMQ_SubscriberThread:
        try:
            subscriber_thread = ZMQ_SubscriberThread(host, port, self._context, request_bgr)
            subscriber_thread.start()
            # Wait for the thread to start and socket to be ready
            if not subscriber_thread._wait_for_start(timeout=1.0):
                raise ConnectionError(f"Subscriber thread failed to start for {host}:{port}")
            return subscriber_thread
        except Exception as e:
            logger_mp.error(f"Failed to create subscriber thread for {host}:{port}: {e}")
            raise

    def _get_subscriber_thread(self, host: str, port: int, request_bgr: bool = False) -> ZMQ_SubscriberThread:
        key = (host, port)
        with self._lock:
            if key not in self._subscriber_threads:
                self._subscriber_threads[key] = self._create_subscriber_thread(host, port, request_bgr)
            return self._subscriber_threads[key]

    # --------------------------------------------------------
    # public api
    # --------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "ZMQ_SubscriberManager":
        """Get or create the singleton instance with thread safety."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def subscribe(self, host: str, port: int, request_bgr: bool = False) -> TeleImage:
        """Receive the latest message from the specified subscriber.
        Args:
            host: The server address
            port: The port number
            request_bgr: Whether to request BGR decoding

        Returns:
            The latest message as a TeleImage object containing current fps, raw bytes and decoded BGR image (if enabled).
        """
        if not self._running:
            raise RuntimeError("SubscriberManager is closed.")

        subscriber_thread = self._get_subscriber_thread(host, port, request_bgr=request_bgr)
        return subscriber_thread.recv()

    def close(self) -> None:
        """Close all subscribers."""
        self._running = False
        # close all subscribers
        with self._lock:
            for key, subscriber in self._subscriber_threads.items():
                try:
                    subscriber.stop()
                except Exception as e:
                    logger_mp.error(f"Error stopping subscriber at {key[0]}:{key[1]}: {e}")
            self._subscriber_threads.clear()

# ========================================================
# ZMQ response
# ========================================================
class ZMQ_Responser:
    """ ZMQ REP socket to respond with camera configuration upon request."""
    def __init__(self, cam_config, host: str = "0.0.0.0", port: int = 60000):
        """
        Args:
            cam_config: The cam_config to send in response to requests.
            host: Host/IP to bind.
            port: TCP port to bind.
            poll_timeout: Timeout in milliseconds for poll() to check for requests.
        """
        self._cam_config = cam_config
        self._host = host
        self._port = port
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REP)
        self._socket.bind(f"tcp://{self._host}:{self._port}")
        self._running = True

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger_mp.info(f"[Responser] Camera Config Responser initialized at {self._host}:{self._port}")

    def _run(self):
        poller = zmq.Poller()
        poller.register(self._socket, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=200))
                if self._socket in socks and socks[self._socket] == zmq.POLLIN:
                    _ = self._socket.recv()  # receive request
                    self._socket.send_json(self._cam_config)
            except zmq.ZMQError as e:
                if not self._running:
                    break  # normal exit when stopping
                logger_mp.error(f"ZMQError in Responser: {e}")
            except Exception as e:
                logger_mp.error(f"Unexpected error in Responser: {e}")
    # --------------------------------------------------------
    # public api
    # --------------------------------------------------------
    def get_port(self):
        return self._port

    def stop(self):
        """Stop the Responser thread and close ZMQ resources."""
        self._running = False
        self._thread.join(timeout=1)
        if self._thread.is_alive():
            logger_mp.warning("Responser thread did not stop gracefully")
        try:
            self._socket.close()
            self._context.term()
        except Exception as e:
            logger_mp.warning(f"Error closing Responser socket: {e}")


class ZMQ_RGBDResponser:
    """ ZMQ REP socket to respond with synchronized RGB+Depth data upon request."""
    def __init__(self, image_server, host: str = "0.0.0.0", port: int = 60001):
        """
        Args:
            image_server: Reference to ImageServer instance to access cameras
            host: Host/IP to bind
            port: TCP port to bind
        """
        self._image_server = image_server
        self._host = host
        self._port = port
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REP)
        self._socket.bind(f"tcp://{self._host}:{self._port}")
        self._running = True

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger_mp.info(f"[RGBD Responser] RGBD Responser initialized at {self._host}:{self._port}")

    def _run(self):
        poller = zmq.Poller()
        poller.register(self._socket, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=200))
                if self._socket in socks and socks[self._socket] == zmq.POLLIN:
                    request = self._socket.recv_json()  # receive request
                    cam_topic = request.get("camera", "head_camera")

                    # Get camera object
                    camera = self._image_server._cameras.get(cam_topic)

                    if camera is None:
                        error_response = {"error": f"Camera {cam_topic} not found"}
                        self._socket.send_json(error_response)
                        continue

                    # Check if camera supports depth (RealSense only)
                    # Use hasattr to check for depth capabilities instead of isinstance
                    if not hasattr(camera, '_enable_depth') or not camera._enable_depth:
                        error_response = {"error": f"Camera {cam_topic} does not support depth"}
                        self._socket.send_json(error_response)
                        continue

                    # Get RGB frame (JPEG bytes)
                    rgb_jpeg = camera.get_jpeg_bytes()

                    # Get depth frame (raw bytes)
                    depth_bytes = camera.get_depth_frame()

                    if rgb_jpeg is None or depth_bytes is None:
                        error_response = {"error": "No frame data available"}
                        self._socket.send_json(error_response)
                        continue

                    # Send response as multipart message
                    # Part 1: Metadata (JSON)
                    metadata = {
                        "camera": cam_topic,
                        "rgb_size": len(rgb_jpeg),
                        "depth_size": len(depth_bytes),
                        "depth_shape": list(camera._img_shape),  # [H, W]
                        "depth_scale": camera.g_depth_scale if hasattr(camera, 'g_depth_scale') else 1.0
                    }
                    self._socket.send_json(metadata, zmq.SNDMORE)

                    # Part 2: RGB JPEG bytes
                    self._socket.send(rgb_jpeg, zmq.SNDMORE)

                    # Part 3: Depth raw bytes
                    self._socket.send(depth_bytes)

            except zmq.ZMQError as e:
                if not self._running:
                    break  # normal exit when stopping
                logger_mp.error(f"ZMQError in RGBD Responser: {e}")
            except Exception as e:
                logger_mp.error(f"Unexpected error in RGBD Responser: {e}")
                try:
                    error_response = {"error": str(e)}
                    self._socket.send_json(error_response)
                except:
                    pass

    def stop(self):
        """Stop the RGBD Responser thread and close ZMQ resources."""
        self._running = False
        self._thread.join(timeout=1)
        if self._thread.is_alive():
            logger_mp.warning("RGBD Responser thread did not stop gracefully")
        try:
            self._socket.close()
            self._context.term()
        except Exception as e:
            logger_mp.warning(f"Error closing RGBD Responser socket: {e}")


# ========================================================
# ZMQ request
# ========================================================
class ZMQ_Requester:
    """ ZMQ REQ socket to request camera configuration from server. If server is unreachable,
        try to load from local cam_config_client.yaml or cam_config_server.yaml."""
    def __init__(self, host: str, port: int):
        """
        Args:
            host: IP or hostname of the server.
            port: TCP port of the server.
        """
        self._host = host
        self._port = port
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REQ)
        self._socket.setsockopt(zmq.LINGER, 0)  # do not wait on close
        self._socket.connect(f"tcp://{self._host}:{self._port}")

        self._poller = zmq.Poller()
        self._poller.register(self._socket, zmq.POLLIN)

        self._current_dir = os.path.dirname(os.path.abspath(__file__))
        self._package_dir = os.path.abspath(os.path.join(self._current_dir, "../../"))
        self._config_client_path = os.path.join(self._package_dir, "cam_config_client.yaml")
        self._config_server_path = os.path.join(self._package_dir, "cam_config_server.yaml")
    # --------------------------------------------------------
    # public api
    # --------------------------------------------------------
    def request(self) -> Optional[Dict[str, Any]]:
        cam_config = None
        try:
            msg = b"GET_DATA"
            self._socket.send(msg)
            socks = dict(self._poller.poll(timeout=1000))

            if self._socket in socks and socks[self._socket] == zmq.POLLIN:
                cam_config = self._socket.recv_json()
                if cam_config is not None:
                    logger_mp.info(f"Received camera config from server {self._host}:{self._port}")
                    with open(self._config_client_path, "w") as f:
                        yaml.safe_dump(cam_config, f, sort_keys=False, allow_unicode=True)
                    logger_mp.info(f"Saved camera config to local {self._config_client_path}")
            else:
                logger_mp.warning(f"Request to {self._host}:{self._port} timed out or no response, using local config.")
                if os.path.exists(self._config_client_path):
                    try:
                        with open(self._config_client_path, "r") as f:
                            cam_config = yaml.safe_load(f)
                        logger_mp.info(f"Loaded camera config from local {self._config_client_path}")
                    except Exception as e:
                        logger_mp.warning(f"Failed to load local cam_config_client.yaml: {e}")
                elif os.path.exists(self._config_server_path):
                    try:
                        with open(self._config_server_path, "r") as f:
                            cam_config = yaml.safe_load(f)
                        logger_mp.info(f"Loaded camera config from local {self._config_server_path}")
                    except Exception as e:
                        logger_mp.warning(f"Failed to load local cam_config_server.yaml: {e}")
                else:
                    logger_mp.error("No camera configuration file found locally.")
            return cam_config
        except Exception as e:
            logger_mp.error(f"Unexpected error in Requester: {e}")
            return cam_config

    def close(self):
        """Close the requester socket and terminate context."""
        try:
            self._socket.close()
            self._context.term()
        except Exception as e:
            logger_mp.warning(f"Error closing Requester socket: {e}")


class ZMQ_RGBDRequester:
    """ ZMQ REQ socket to request synchronized RGB+Depth frames from server."""
    def __init__(self, host: str, port: int = 60001):
        """
        Args:
            host: IP or hostname of the server
            port: TCP port of the RGBD server (default: 60001)
        """
        self._host = host
        self._port = port
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REQ)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(f"tcp://{self._host}:{self._port}")

        self._poller = zmq.Poller()
        self._poller.register(self._socket, zmq.POLLIN)

    def request_rgbd(self, camera="head_camera", timeout=1000) -> Optional[Tuple[np.ndarray, np.ndarray, dict]]:
        """
        Request synchronized RGB and Depth frames.

        Args:
            camera: Camera topic name (e.g., "head_camera")
            timeout: Request timeout in milliseconds

        Returns:
            Tuple of (rgb_image, depth_image, metadata) or None if request fails
            - rgb_image: BGR numpy array (H, W, 3) uint8
            - depth_image: Depth numpy array (H, W) uint16
            - metadata: dict with camera info and depth_scale
        """
        try:
            request = {"camera": camera}
            self._socket.send_json(request)

            socks = dict(self._poller.poll(timeout=timeout))

            if self._socket in socks and socks[self._socket] == zmq.POLLIN:
                # Receive multipart message
                # Part 1: Metadata
                metadata = self._socket.recv_json()

                # Check for error
                if "error" in metadata:
                    logger_mp.error(f"RGBD Request error: {metadata['error']}")
                    return None

                # Part 2: RGB JPEG bytes
                rgb_jpeg = self._socket.recv()

                # Part 3: Depth raw bytes
                depth_bytes = self._socket.recv()

                # Decode RGB
                np_img = np.frombuffer(rgb_jpeg, dtype=np.uint8)
                rgb_image = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

                # Decode depth
                depth_shape = tuple(metadata['depth_shape'])
                depth_image = np.frombuffer(depth_bytes, dtype=np.uint16).reshape(depth_shape)

                # logger_mp.info(f"Received RGBD frame from {camera}: RGB {rgb_image.shape}, Depth {depth_image.shape}")
                return rgb_image, depth_image, metadata
            else:
                logger_mp.warning(f"RGBD Request to {self._host}:{self._port} timed out")
                return None

        except Exception as e:
            logger_mp.error(f"Unexpected error in RGBD Request: {e}")
            return None

    def close(self):
        """Close the requester socket and terminate context."""
        try:
            self._socket.close()
            self._context.term()
        except Exception as e:
            logger_mp.warning(f"Error closing RGBD Requester socket: {e}")


# ========================================================
# image client
# ========================================================
class ImageClient:
    def __init__(self, host="192.168.123.164", request_port=60000, rgbd_request_port=60001, request_bgr: bool = False):
        """
        Args:
            server_address:   IP address of image host server
            request_port:     TCP port for camera configuration request
            request_bgr:      Whether to request BGR decoding for subscribers
        """
        self._host = host
        self._request_port = request_port
        self._request_bgr = request_bgr

        # subscriber and requester setup
        self._subscriber_manager = ZMQ_SubscriberManager.get_instance()
        self._requester  = ZMQ_Requester(self._host, self._request_port)
        self._cam_config = self._requester.request()

        if self._cam_config is None:
            raise RuntimeError("Failed to get camera configuration.")

        if self._cam_config['head_camera']['enable_zmq']:
            self._subscriber_manager.subscribe(self._host, self._cam_config['head_camera']['zmq_port'], request_bgr=self._request_bgr)

        if  self._cam_config.get('left_wrist_camera') and self._cam_config['left_wrist_camera']['enable_zmq']:
            self._subscriber_manager.subscribe(self._host, self._cam_config['left_wrist_camera']['zmq_port'], request_bgr=self._request_bgr)

        if self._cam_config.get('right_wrist_camera') and self._cam_config['right_wrist_camera']['enable_zmq']:
            self._subscriber_manager.subscribe(self._host, self._cam_config['right_wrist_camera']['zmq_port'], request_bgr=self._request_bgr)

        if not self._cam_config['head_camera']['enable_zmq'] and not self._cam_config['head_camera']['enable_webrtc']:
            logger_mp.warning("[Image Client] NOTICE! Head camera is not enabled on both ZMQ and WebRTC.")

        # RGBD requester setup (for synchronized depth+RGB requests)
        self._rgbd_requester = ZMQ_RGBDRequester(self._host, port=rgbd_request_port)

    # --------------------------------------------------------
    # public api
    # --------------------------------------------------------
    def get_cam_config(self):
        return self._cam_config

    def get_intrinsics(self, camera: str = 'head_camera') -> Optional[dict]:
        """
        返回指定相机的 intrinsics dict，包含 fx, fy, ppx, ppy, width, height, coeffs。
        仅在 server 启用了 RealSense 且写入了 intrinsics 时有效。
        """
        cam_cfg = self._cam_config.get(camera, {})
        return cam_cfg.get('intrinsics', None)

    def get_intrinsics_matrix(self, camera: str = 'head_camera') -> Optional[np.ndarray]:
        """
        返回 3x3 intrinsics 矩阵 K。
        """
        intr = self.get_intrinsics(camera)
        if intr is None:
            return None
        K = np.array([
            [intr['fx'],    0,          intr['ppx']],
            [0,             intr['fy'], intr['ppy']],
            [0,             0,          1          ]
        ], dtype=np.float32)
        return K

    def get_head_frame(self):
        return self._subscriber_manager.subscribe(self._host, self._cam_config['head_camera']['zmq_port'], request_bgr=self._request_bgr)

    def get_left_wrist_frame(self):
        return self._subscriber_manager.subscribe(self._host, self._cam_config['left_wrist_camera']['zmq_port'], request_bgr=self._request_bgr)

    def get_right_wrist_frame(self):
        return self._subscriber_manager.subscribe(self._host, self._cam_config['right_wrist_camera']['zmq_port'], request_bgr=self._request_bgr)


    def get_rgbd_frame(self, camera="head_camera", timeout=1000):
        """
        Get synchronized RGB and Depth frames from a RealSense camera.

        Args:
            camera: Camera topic name (e.g., "head_camera", "left_wrist_camera", "right_wrist_camera")
            timeout: Request timeout in milliseconds (default: 1000)

        Returns:
            Tuple of (rgb_image, depth_image, metadata) or None if request fails
            - rgb_image: BGR numpy array (H, W, 3) uint8
            - depth_image: Depth numpy array (H, W) uint16
            - metadata: dict with camera info and depth_scale
        """
        return self._rgbd_requester.request_rgbd(camera, timeout)

    def close(self):
        self._subscriber_manager.close()
        logger_mp.info("Image client has been closed.")

def main():
    # command line args
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=str, default='192.168.123.164', help='IP address of image server')
    parser.add_argument('--request_port', type=int, default=60000)
    parser.add_argument('--rgbd_request_port', type=int, default=60001)
    args = parser.parse_args()

    # Example usage with three camera streams
    client = ImageClient(host=args.host, request_bgr=True)
    cam_config = client.get_cam_config()

    running = True
    while running:
        if cam_config['head_camera']['enable_zmq']:
            head_img = client.get_head_frame()
            if head_img.bgr is not None:
                logger_mp.info(f"Head Camera FPS: {head_img.fps:.2f}")
                logger_mp.debug(f"Head Camera Shape: {cam_config['head_camera']['image_shape']}")
                logger_mp.debug(f"Head Camera Binocular: {cam_config['head_camera']['binocular']}")
                cv2.imwrite("head_img.png", head_img.bgr)

        if cam_config.get('left_wrist_camera') and cam_config['left_wrist_camera']['enable_zmq']:
            left_wrist_img = client.get_left_wrist_frame()
            if left_wrist_img.bgr is not None:
                logger_mp.info(f"Left Wrist Camera FPS: {left_wrist_img.fps:.2f}")
                logger_mp.debug(f"Left Wrist Camera Shape: {cam_config['left_wrist_camera']['image_shape']}")
                cv2.imshow("Left Wrist Camera", left_wrist_img.bgr)

        if cam_config.get('right_wrist_camera') and cam_config['right_wrist_camera']['enable_zmq']:
            right_wrist_img = client.get_right_wrist_frame()
            if right_wrist_img.bgr is not None:
                logger_mp.info(f"Right Wrist Camera FPS: {right_wrist_img.fps:.2f}")
                logger_mp.debug(f"Right Wrist Camera Shape: {cam_config['right_wrist_camera']['image_shape']}")
                cv2.imshow("Right Wrist Camera", right_wrist_img.bgr)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            logger_mp.info("Exiting image client on user request.")
            running = False
            # clean up
            client.close()
            cv2.destroyAllWindows()
        # Small delay to prevent excessive CPU usage
        time.sleep(0.002)

if __name__ == "__main__":
    main()
