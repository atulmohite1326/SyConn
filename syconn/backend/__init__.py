# -*- coding: utf-8 -*-
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max Planck Institute of Neurobiology, Martinsried, Germany
# Authors: Philipp Schubert, Sven Dorkenwald, Joergen Kornfeld

from ..global_params import backend
from .base import FSBase, BTBase
from ..handler.logger import log_main

# init backend
if backend == 'FS':
    StorageClass = FSBase
elif backend == 'BT':
    StorageClass = BTBase
# init log
log_backend = log_main

__all__ = ['StorageClass', 'log_backend']

