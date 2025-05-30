#!/usr/bin/env python

# Copyright (c) 2024 Óscar Pons Fernández <oscarpf22@gmail.com>
# Copyright (c) 2024 Alberto J. Tudela Roldán <ajtudela@gmail.com>
# Copyright (c) 2024 Grupo Avispa, DTE, Universidad de Málaga
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http:#www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# Python
import time
import numpy as np
import torch
import cv2
from cv_bridge import CvBridge, CvBridgeError

# ROS 2
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSHistoryPolicy, QoSReliabilityPolicy
from sensor_msgs.msg import Image
from sensor_msgs.msg import CameraInfo

# DepthAnything V2
from depth_anything_v2.metric_depth.depth_anything_v2.dpt import DepthAnythingV2


class DepthAnythingROS(Node):
    """DepthAnythingROS node

    This node subscribes to an image topic and publishes the image depth image estimation.

    Parameters
    ----------
        image_topic : str
            Topic where the image will be subscribed.
        depth_image_topic : str
            Topic where the raw depth image will be published.
        camera_info_topic : str
            Topic where the camera info will be published.
        device : str
            Device to use for the inference (cpu or cuda).
        model_file : str
            Path to the model.
        encoder : str
            Encoder to use for the model (vits, vitb or vitl).
        max_depth : double
            Maximum distance in meters that is in view of the camera. (100 if outdoors)

    Subscribers
    ----------
        image_topic : sensor_msgs.msg.Image
            Image topic where the rgb image will be subscribed.
        camera_info_sub : sensor_msgs.msg.Image
            Image topic where the camera info will be subscribed.

    Publishers
    ----------
        depth : sensor_msgs.msg.Image
            Image topic where the depth image will be published.
        camera_info_pub : sensor_msgs.msg.Image
            Image topic where the camera info will be published.

    Methods
    -------
        __init__(self)
            Initializes the node.
        get_params(self)
            Gets the ros2 parameters.
        image_callback(self, image_msg: Image)
            Callback function for the image topic.
    """

    def __init__(self):
        super().__init__('depth_anything')
        self.bridge = CvBridge()

        # Get parameters
        self.get_params()
        # Check device selected and if gpu is available
        if self.device != 'cpu':
            if not torch.cuda.is_available():
                self.get_logger().info(f'Device could not be set to: [{self.device}] ...')
                self.device = "cpu"
        self.get_logger().info(f'Setting device to: [{self.device}]')

        # Model initialization
        if self.encoder == 'vits':
            self.model = DepthAnythingV2(encoder=self.encoder, features=64,
                                         out_channels=[48, 96, 192, 384], max_depth=self.max_depth)
        elif self.encoder == 'vitb':
            self.model = DepthAnythingV2(encoder=self.encoder, features=128,
                                         out_channels=[96, 192, 384, 768], max_depth=self.max_depth)
        elif self.encoder == 'vitl':
            self.model = DepthAnythingV2(encoder=self.encoder, features=256,
                                         out_channels=[256, 512, 1024, 1024], max_depth=self.max_depth)
        else:
            self.get_logger().error(
                f'nWrong type of encoder: [{self.encoder}]. Must be vits, vitb or vitl')
        self.model.load_state_dict(torch.load(self.model_file, map_location=self.device))
        self.model.to(self.device).eval()

        # Create common publishers
        sensor_qos_profile = QoSProfile(
            durability=QoSDurabilityPolicy.VOLATILE,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10)
        self.depth_image_pub = self.create_publisher(
            Image, self.depth_image_topic, sensor_qos_profile)
        self.camera_info_pub = self.create_publisher(
            CameraInfo, self.camera_info_pub_topic, sensor_qos_profile)

        # Create subscribers
        self.image_sub = self.create_subscription(
            Image, self.image_topic, self.image_callback, sensor_qos_profile)
        self.camera_info_sub = self.create_subscription(
            CameraInfo, self.camera_info_sub_topic, self.camera_info_sub_callback, sensor_qos_profile)

    def get_params(self) -> None:
        """Get the parameters from the parameter server.
        """
        # Declare and acquire parameters
        self.declare_parameter('image_topic', 'camera/color/image_raw')
        self.image_topic = self.get_parameter(
            'image_topic').get_parameter_value().string_value
        self.get_logger().info(
            f'The parameter image_topic is set to: [{self.image_topic}]')

        self.declare_parameter('depth_image_topic', 'depth')
        self.depth_image_topic = self.get_parameter(
            'depth_image_topic').get_parameter_value().string_value
        self.get_logger().info(
            f'The parameter depth_image_topic is set to: [{self.depth_image_topic}]')
        
        self.declare_parameter('camera_info_sub_topic', 'camera_info')
        self.camera_info_sub_topic = self.get_parameter(
            'camera_info_sub_topic').get_parameter_value().string_value
        self.get_logger().info(
            f'The parameter camera_info_sub_topic is set to: [{self.camera_info_sub_topic}]')
        
        self.declare_parameter('camera_info_pub_topic', 'camera_info')
        self.camera_info_pub_topic = self.get_parameter(
            'camera_info_pub_topic').get_parameter_value().string_value
        self.get_logger().info(
            f'The parameter camera_info_pub_topic is set to: [{self.camera_info_pub_topic}]')

        self.declare_parameter('device', 'cuda:0')
        self.device = self.get_parameter(
            'device').get_parameter_value().string_value
        self.get_logger().info(
            f'The parameter device is set to: [{self.device}]')

        self.declare_parameter('model_file', 'depth_anything_v2_vits.pth')
        self.model_file = self.get_parameter(
            'model_file').get_parameter_value().string_value
        self.get_logger().info(
            f'The parameter model_file is set to: [{self.model_file}]')

        self.declare_parameter('encoder', 'vits')
        self.encoder = self.get_parameter(
            'encoder').get_parameter_value().string_value
        self.get_logger().info(
            f'The parameter encoder is set to: [{self.encoder}]')
        
        self.declare_parameter('max_depth', 20.0)
        self.max_depth = self.get_parameter(
            'max_depth').get_parameter_value().double_value
        self.get_logger().info(
            f'The parameter max_depth is set to: [{self.max_depth}]')

    def image_callback(self, image_msg: Image) -> None:
        """Publishes the image with the detections.

        Args:
            image_msg (Image): Image message.
        """

        # Only detect object if there's any subscriber
        if self.depth_image_pub.get_subscription_count() == 0:
            return

        self.get_logger().info(
            f'Subscribed to depth image topic: [{self.depth_image_topic}]', once=True)
        start_time = time.time()

        # Convert ROS Image to OpenCV Image
        try:
            self.current_image = self.bridge.imgmsg_to_cv2(image_msg, "bgr8")
        except CvBridgeError as e:
            self.get_logger().error(f'Could not convert depth image to OpenCV: {e}')
            return
        
        ## new_width = 640//2
        ## new_height = 360//2
        ## self.current_image = cv2.resize(self.current_image, (new_width, new_height))  
        
        # Perform inference
        image_size = 360
        
        depth = self.model.infer_image(self.current_image, input_size=image_size)
        self.get_logger().info(
            f'Maximum distance: {depth.max()}, Minimum distance: {depth.min()}')
        depth = depth.max() - depth + depth.min()
        ## 
        ## # Scale entire depth map using the table edge in current setup as of April 14, 2025 2PM
        ## if (self.max_depth):
        ##     scale = 2.4/depth[int(new_height//2), int(new_width//2)]
        ##     depth = depth*scale

        end_time = time.time()
        execution_time = end_time - start_time
        self.get_logger().info(f"Depth estimation took: {execution_time*1000:.1f} ms")

        # Convert OpenCV Images to ROS Image and publish it
        try:
            ros_image = self.bridge.cv2_to_imgmsg(depth, "32FC1", image_msg.header)
            self.depth_image_pub.publish(ros_image)
        except CvBridgeError as e:
            print(e)
            
        try:
            camera_info = self.camera_info_from_source
            camera_info.header = image_msg.header
            camera_info.width = 640
            camera_info.height = 360
            for i, k in enumerate(camera_info.k):
                if camera_info.k[i]:
                    camera_info.k[i] = k
                    
            for i, p in enumerate(camera_info.p):
                if camera_info.p[i]:
                    camera_info.p[i] = p
            self.camera_info_pub.publish(camera_info)
        except AttributeError as e:
            print(e)
            
    def camera_info_sub_callback(self, camera_info: CameraInfo) -> None:
        self.camera_info_from_source = camera_info


def main(args=None):
    rclpy.init(args=args)
    node = DepthAnythingROS()
    rclpy.spin(node)

    # Destroy the node explicitly
    # (optional - otherwise it will be done automatically
    # when the garbage collector destroys the node object)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()