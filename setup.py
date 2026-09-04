from glob import glob

from setuptools import find_packages, setup

package_name = 'turtlesim_image_painter'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name, ['LICENSE']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['Pillow>=9.0', 'PyYAML>=5.4', 'setuptools'],
    zip_safe=True,
    maintainer='Pratik Mahankal',
    maintainer_email='pratik.mahankal14@gmail.com',
    description=(
        'Convert raster images into pixel-art painting plans for turtlesim.'),
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'painter = turtlesim_image_painter.painter:main',
            'process_image = process_image:main',
        ],
    },
    py_modules=['process_image'],
)
