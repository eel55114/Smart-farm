#!/usr/bin/env python3
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    # 1. 공통 환경 변수 및 실행 인자(Argument) 설정
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    
    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation (Gazebo) clock if true (e.g., use_sim_time:=true)'
    )

    pkg_remote_dir = get_package_share_directory('turtlebot3_remote')

    
    include_nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_remote_dir, 'launch', 'navigation2.launch.py')
        ),
        launch_arguments={'use_sim_time': use_sim_time}.items()
    )


    node_main = Node(
        package='turtlebot3_remote',
        executable='turtlebot3_main',
        name='turtlebot3_main',
        parameters=[{'use_sim_time': use_sim_time}],
        output='screen'
    )

    node_human_publisher = Node(
        package='turtlebot3_remote',
        executable='turtlebot3_human_publisher',
        name='turtlebot3_human_publisher',
        output='screen'
    )
    
    
    node_map_publish = Node(
        package='turtlebot3_remote',
        executable='turtlebot3_map_publish',
        name='turtlebot3_map_publish',
        parameters=[{'use_sim_time': use_sim_time}],
        output='screen'
    )


    node_test_gui = Node(
        package='turtlebot3_remote',
        executable='turtlebot3_test_gui',
        name='turtlebot3_test_gui',
        parameters=[{'use_sim_time': use_sim_time}],
        output='screen'
    )


    return LaunchDescription([
        declare_use_sim_time,
        include_nav2_launch,
        node_main,
        node_map_publish,
        node_test_gui,
        node_human_publisher
    ])
