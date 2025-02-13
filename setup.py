from setuptools import find_packages, setup
import numpy
import os

try:
    from Cython.Build import cythonize
    cython_out = cythonize(["syconn/*/*.pyx"], include_path=[numpy.get_include(),],
                           compiler_directives={
                                'language_level': 3, 'boundscheck': False,
                                'wraparound': False, 'initializedcheck': False,
                                'cdivision': False, 'overflowcheck': True})
    setup_requires = ["pytest-runner", "cython>=0.23"]
except ImportError as e:
    print("WARNING: Could not build cython modules. {}".format(e))
    setup_requires = ["pytest-runner"]
    cython_out = None
readme_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'README.md')
with open(readme_file) as f:
    readme = f.read()

config = {
    'description': 'Analysis pipeline for EM raw data based on deep and '
                   'supervised learning to extract high level biological'
                   'features and connectivity. ',
    'author': 'Philipp Schubert, Sven Dorkenwald, Joergen Kornfeld',
    'url': 'https://structuralneurobiologylab.github.io/SyConn/',
    'download_url': 'https://github.com/StructuralNeurobiologyLab/SyConn.git',
    'author_email': 'pschubert@neuro.mpg.de',
    'version': '0.2',
    'license': 'GPLv2',
    'install_requires': [
        # included in requirements.txt, but excluded here to enable readthedocs build.
                        #'knossos_utils', 'elektronn3', 'openmesh==1.1.3',
                         'numpy==1.16.0', 'scipy', 'lz4', 'h5py', 'networkx', 'ipython<7.0.0',
                         'configobj', 'fasteners', 'flask', 'coloredlogs',
                         'opencv-python', 'pyopengl', 'scikit-learn==0.19.1',
                         'scikit-image==0.14.2', 'plyfile', 'termcolor',
                         'pytest', 'tqdm', 'dill', 'zmesh', 'seaborn',
                         'pytest-runner', 'prompt-toolkit<2.0', 'numba==0.41.0',
                         'llvmlite==0.26.0', 'matplotlib', 'vtki'],
    #numba/llvmluite
    # requirements due to https://github.com/numba/numba/issues/3666 in @jit compilation of 'id2rgb_array_contiguous' (in multiviews.py)
    'name': 'SyConn',
    'dependency_links': ['https://github.com/knossos-project/knossos_utils'
                         '/tarball/dev#egg=knossos_utils',
                         'https://github.com/ELEKTRONN/elektronn3/'
                         'tarball/phil/#egg=elektronn3'],
    'packages': find_packages(exclude=['scripts']), 'long_description': readme,
    'setup_requires': setup_requires, 'tests_require': ["pytest", ],
    # this will compile all files within directories in syconn/
     'ext_modules': cython_out,
    'include_dirs': [numpy.get_include(), ],

}

setup(**config)
