#!/bin/bash
# cd to the SyConn directory an run this file via 'sh install.sh'

echo y | conda install cmake
echo y | conda install vigra -c conda-forge
echo y | conda install -c conda-forge opencv
echo y | conda install mesa -c menpo
echo y | conda install osmesa -c menpo
echo y | conda install freeglut
echo y | conda install pyopengl
echo y | conda install snappy
echo y | conda install python-snappy
echo y | conda install tensorboard tensorflow
echo y | conda install llvmlite=0.26.0
echo y | conda install gcc_impl_linux-64 gcc_linux-64 gxx_impl_linux-64 gxx_linux-64


pip install -r requirements.txt
pip install -e .

echo y | conda install -c conda-forge sip=4.18.1  # https://github.com/CadQuery/CQ-editor/issues/1