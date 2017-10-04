# -*- coding: utf-8 -*-
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max-Planck-Institute for Medical Research, Heidelberg, Germany
# Authors: Sven Dorkenwald, Philipp Schubert, Joergen Kornfeld

from collections import defaultdict
import warnings
import numpy as np
import os
import shutil
import tempfile
import zipfile
import cPickle as pickle
from knossos_utils.skeleton_utils import loadj0126NML
from knossos_utils.skeleton import Skeleton, SkeletonAnnotation, SkeletonNode
import re
import fasteners
import signal
import logging

__all__ = ["get_filepaths_from_dir", "write_obj2pkl", "load_pkl2obj",
           "write_data2kzip", "remove_from_zip", "chunkify", "flatten_list",
           "get_skelID_from_path", "write_txt2kzip"]


def argsort(seq):
    # http://stackoverflow.com/questions/3071415/efficient-method-to-calculate-the-rank-vector-of-a-list-in-python
    return sorted(range(len(seq)), key=seq.__getitem__)


def group_ids_to_so_storage(ids, params, significant_digits=5):
    id_dict = defaultdict(list)
    param_dicts = [defaultdict(list) for _ in range(len(params))]
    for i_id in range(len(ids)):
        this_id = ids[i_id]
        this_id_str = "%.5d" % this_id
        id_dict[this_id_str[-significant_digits:]].append(this_id)
        for i_param in range(len(params)):
            param_dicts[i_param][this_id_str[-significant_digits:]].\
                append(params[i_param][i_id])

    return [id_dict] + param_dicts


def get_paths_of_skelID(id_list, traced_skel_dir):
    """Gather paths to kzip of skeletons with ID in id_list

    Parameters
    ----------
    id_list: list of str
        skeleton ID's
    traced_skel_dir: str
        directory of mapped skeletons

    Returns
    -------
    list of str
        paths of skeletons in id_list
    """
    mapped_skel_paths = get_filepaths_from_dir(traced_skel_dir)
    mapped_skel_ids = re.findall('iter_\d+_(\d+)', ''.join(mapped_skel_paths))
    wanted_paths = []
    for skelID in id_list:
        try:
            path = mapped_skel_paths[mapped_skel_ids.index(str(skelID))]
            wanted_paths.append(path)
        except:
            wanted_paths.append(None)
    return wanted_paths


def coordpath2anno(coords, scaling=(10, 10, 20), add_edges=True):
    """
    Creates skeleton from scaled coordinates, assume coords are in order for
    edge creation.

    Parameters
    ----------
    coords : np.array
        scaled cooridnates

    Returns
    -------
    SkeletonAnnotation
    """
    anno = SkeletonAnnotation()
    anno.scaling = scaling
    scaling = np.array(scaling, dtype=np.int)
    rep_nodes = []
    coords = np.array(coords, dtype=np.int)
    for c in coords:
        unscaled_c = c / scaling
        n = SkeletonNode().from_scratch(anno, unscaled_c[0], unscaled_c[1],
                                        unscaled_c[2])
        anno.addNode(n)
        rep_nodes.append(n)
    if add_edges:
        for i in range(1, len(rep_nodes)):
            anno.addEdge(rep_nodes[i-1], rep_nodes[i])
    return anno


def get_filepaths_from_dir(directory, ending='k.zip', recursively=False):
    """
    Collect all files with certain ending from directory.

    Parameters
    ----------
    directory: str
        path to lookup directory
    ending: str
        ending of files
    recursively: boolean
        add files from subdirectories

    Returns
    -------
    list of str
        paths to files
    """
    if recursively:
        files = [os.path.join(r, f) for r,s ,fs in
                 os.walk(directory) for f in fs if ending in f[-len(ending):]]
    else:
        files = [os.path.join(directory, f) for f in next(os.walk(directory))[2]
                 if ending in f[-len(ending):]]
    return files


def read_txt_from_zip(zip_fname, fname_in_zip):
    """
    Read text file from zip.

    Parameters
    ----------
    zip_fname : str
    fname_in_zip : str

    Returns
    -------
    str
    """
    with zipfile.ZipFile(zip_fname, allowZip64=True) as z:
        txt = z.read(fname_in_zip)
    return txt


def write_txt2kzip(kzip_path, text, fname_in_zip, force_overwrite=False):
    """
    Write text to file in k.zip.

    Parameters
    ----------
    kzip_path : str
    text : str
    fname_in_zip : str
        name of file when added to zip
    force_overwrite : bool
    """
    with DelayedInterrupt([signal.SIGTERM, signal.SIGINT]):
        if os.path.isfile(kzip_path):
            try:
                if force_overwrite:
                    with zipfile.ZipFile(kzip_path, "w", zipfile.ZIP_DEFLATED,
                                         allowZip64=True) as zf:
                        zf.writestr(fname_in_zip, text)
                else:
                    remove_from_zip(kzip_path, fname_in_zip)
                    with zipfile.ZipFile(kzip_path, "a", zipfile.ZIP_DEFLATED,
                                         allowZip64=True) as zf:
                        zf.writestr(fname_in_zip, text)
            except Exception, e:
                print "Couldn't open file %s for reading and" \
                      " overwriting." % kzip_path, e
        else:
            try:
                with zipfile.ZipFile(kzip_path, "w", zipfile.ZIP_DEFLATED,
                                     allowZip64=True) as zf:
                    zf.writestr(fname_in_zip, text)
            except Exception, e:
                print "Couldn't open file %s for writing." % kzip_path, e


def write_data2kzip(kzip_path, fpath, fname_in_zip=None, force_overwrite=False):
    """
    Write file to k.zip.

    Parameters
    ----------
    kzip_path : str
    fpath : str
    fname_in_zip : str
        name of file when added to zip
    force_overwrite : bool
    """
    file_name = os.path.split(fpath)[1]
    if fname_in_zip is not None:
        file_name = fname_in_zip
    with DelayedInterrupt([signal.SIGTERM, signal.SIGINT]):
        if os.path.isfile(kzip_path):
            try:
                if force_overwrite:
                    with zipfile.ZipFile(kzip_path, "w", zipfile.ZIP_DEFLATED,
                                         allowZip64=True) as zf:
                        zf.write(fpath, file_name)
                else:
                    remove_from_zip(kzip_path, file_name)
                    with zipfile.ZipFile(kzip_path, "a", zipfile.ZIP_DEFLATED,
                                         allowZip64=True) as zf:
                        zf.write(fpath, file_name)
            except Exception, e:
                print "Couldn't open file %s for reading and" \
                      " overwriting." % kzip_path, e
        else:
            try:
                with zipfile.ZipFile(kzip_path, "w", zipfile.ZIP_DEFLATED,
                                     allowZip64=True) as zf:
                    zf.write(fpath, file_name)
            except Exception, e:
                print "Couldn't open file %s for writing." % kzip_path, e
        os.remove(fpath)


def remove_from_zip(zipfname, *filenames):
    """Removes filenames from zipfile

    Parameters
    ----------
    zipfname : str
        Path to zipfile
    filenames : list of str
        files to delete
    """
    with DelayedInterrupt([signal.SIGTERM, signal.SIGINT]):
        tempdir = tempfile.mkdtemp()
        try:
            tempname = os.path.join(tempdir, 'new.zip')
            with zipfile.ZipFile(zipfname, 'r', allowZip64=True) as zipread:
                with zipfile.ZipFile(tempname, 'w', allowZip64=True) as zipwrite:
                    for item in zipread.infolist():
                        if item.filename not in filenames:
                            data = zipread.read(item.filename)
                            zipwrite.writestr(item, data)
            shutil.move(tempname, zipfname)
        finally:
            shutil.rmtree(tempdir)


def write_obj2pkl(path, objects):
    """Writes object to pickle file

    Parameters
    ----------
    objects : object
    path : str
        destianation
    """
    with DelayedInterrupt([signal.SIGTERM, signal.SIGINT]):
        if isinstance(path, str):
            with open(path, 'wb') as output:
                pickle.dump(objects, output, -1)
        else:
            warnings.warn("Write_obj2pkl takes arguments 'path' (str) and "
                          "'objects' (python object).", DeprecationWarning)
            with open(objects, 'wb') as output:
                pickle.dump(path, output, -1)



def load_pkl2obj(path):
    """Loads pickle file of object

    Parameters
    ----------
    path: str
        path of source file

    Returns
    -------
    SegmentationDatasetObject
    """
    with open(path, 'rb') as inp:
        objects = pickle.load(inp)
    return objects


def chunkify(lst, n):
    """
    Splits list into n sub-lists.

    Parameters
    ----------
    lst : list
    n : int

    Returns
    -------

    """
    return [lst[i::n] for i in xrange(n)]


def flatten_list(lst):
    """
    Flattens list of lists.

    Parameters
    ----------
    lst : list of lists

    Returns
    -------
    list
    """
    res = np.array([el for sub in lst for el in sub])
    return res


def get_skelID_from_path(skel_path):
    """
    Parse skeleton ID from filename.

    Parameters
    ----------
    skel_path : str
        path to skeleton

    Returns
    -------
    int
        skeleton ID
    """
    return int(re.findall('iter_0_(\d+)', skel_path)[0])


def safe_copy(src, dest, safe=True):
    """
    Copies file and throws exception if destination exists. Taken from
    Misandrist on Stackoverflow (03/31/17).

    Parameters
    ----------
    src : str
        path to source file
    dest : str
        path to destination file
    safe : bool
        If False, copies file with replacement
    """
    if safe:
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        # Copy the file and automatically close files at the end
        with os.fdopen(fd) as f:
            with open(src) as sf:
                shutil.copyfileobj(sf, f)
    else:
        shutil.copy(src, dest)


# https://gist.github.com/tcwalther/ae058c64d5d9078a9f333913718bba95
# class based on: http://stackoverflow.com/a/21919644/487556
class DelayedInterrupt(object):
    def __init__(self, signals):
        if not isinstance(signals, list) and not isinstance(signals, tuple):
            signals = [signals]
        self.sigs = signals        

    def __enter__(self):
        self.signal_received = {}
        self.old_handlers = {}
        for sig in self.sigs:
            self.signal_received[sig] = False
            self.old_handlers[sig] = signal.getsignal(sig)
            def handler(s, frame):
                self.signal_received[sig] = (s, frame)
                # Note: in Python 3.5, you can use signal.Signals(sig).name
                logging.info('Signal %s received. Delaying KeyboardInterrupt.' % sig)
            self.old_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, handler)

    def __exit__(self, type, value, traceback):
        for sig in self.sigs:
            signal.signal(sig, self.old_handlers[sig])
            if self.signal_received[sig] and self.old_handlers[sig]:
                self.old_handlers[sig](*self.signal_received[sig])