import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'turtlebot3_remote'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        
        # 1. 런치 파일 등록
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        
        # 2. 루트 및 기본 yaml 등록
        (os.path.join('share', package_name), ['nav_tree.xml']),
        (os.path.join('share', package_name, 'yaml'), glob('yaml/*.yaml')),
        
        # 3. [중요] param 폴더 등록 (하위 humble 폴더까지 개별 지정)
        (os.path.join('share', package_name, 'param', 'bringup'), glob('param/bringup/*.yaml')),
        (os.path.join('share', package_name, 'param', 'bringup', 'humble'), glob('param/bringup/humble/*.yaml')),
        (os.path.join('share', package_name, 'param', 'nav2'), glob('param/nav2/*.yaml')),
        (os.path.join('share', package_name, 'param', 'nav2', 'humble'), glob('param/nav2/humble/*.yaml')),
        
        # 4. [추가] map 및 rviz 폴더 등록
        (os.path.join('share', package_name, 'map'), glob('map/*.yaml') + glob('map/*.pgm')),
        (os.path.join('share', package_name, 'rviz'), glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='kim',
    maintainer_email='kim@todo.todo',
    description='TurtleBot3 Remote Navigation Package',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # 터미널에서 실행할 노드 명령어 등록 (각 스크립트 내부의 main 함수 실행)
            'turtlebot3_remote = turtlebot3_remote.turtlebot3_remote:main',
            'turtlebot3_map_publish = turtlebot3_remote.turtlebot3_map_publish:main',
            'turtlebot3_test_gui = turtlebot3_remote.turtlebot3_test_gui:main',
        ],
    },
)
