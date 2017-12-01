# -*- coding: utf-8 -*-
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max-Planck-Institute for Medical Research, Heidelberg, Germany
# Authors: Sven Dorkenwald, Philipp Schubert, Joergen Kornfeld

import cPickle as pkl
import numpy as np
import re
import glob
import os
from collections import Counter
from multiprocessing.pool import ThreadPool

from knossos_utils import knossosdataset

from ..reps import segmentation
from ..config import parser
from ..handler.basics import load_pkl2obj, write_obj2pkl
try:
    from knossos_utils import mergelist_tools
except ImportError:
    from knossos_utils import mergelist_tools_fallback as mergelist_tools
skeletopyze_available = False
attempted_skeletopyze_import = False
try:
    import skeletopyze
    skeletopyze_available = True
except:
    skeletopyze_available = False
    # print "skeletopyze not found - you won't be able to compute skeletons. " \
    #       "Install skeletopyze from https://github.com/funkey/skeletopyze"
from ..proc.ssd_assembly import assemble_from_mergelist
from ..mp import qsub_utils as qu
from .super_segmentation_object import SuperSegmentationObject
from ..mp import shared_mem as sm
script_folder = os.path.abspath(os.path.dirname(__file__) + "/../QSUB_scripts/")
try:
    default_wd_available = True
    from ..config.global_params import wd
except:
    default_wd_available = False


class SuperSegmentationDataset(object):
    def __init__(self, working_dir=None, version=None, version_dict=None,
                 sv_mapping=None, scaling=None, config=None):
        """

        Parameters
        ----------
        working_dir : str
        version : str
        version_dict : dict
        sv_mapping : dict or str
        scaling : tuple
        """
        self.ssv_dict = {}
        self.mapping_dict = {}
        self.reversed_mapping_dict = {}

        self._id_changer = []
        self._ssv_ids = None
        self._config = config

        if working_dir is None:
            if default_wd_available:
                self._working_dir = wd
            else:
                raise Exception("No working directory (wd) specified in config")
        else:
            self._working_dir = working_dir

        if scaling is None:
            try:
                self._scaling = \
                    np.array(self.config.entries["Dataset"]["scaling"])
            except:
                self._scaling = np.array([1, 1, 1])
        else:
            self._scaling = scaling

        if version is None:
            try:
                self._version = self.config.entries["Versions"][self.type]
            except:
                raise Exception("unclear value for version")
        elif version == "new":
            other_datasets = glob.glob(self.working_dir + "/%s_*" % self.type)
            max_version = -1
            for other_dataset in other_datasets:
                other_version = \
                    int(re.findall("[\d]+",
                                   os.path.basename(other_dataset))[-1])
                if max_version < other_version:
                    max_version = other_version

            self._version = max_version + 1
        else:
            self._version = version

        if version_dict is None:
            try:
                self.version_dict = self.config.entries["Versions"]
            except:
                raise Exception("No version dict specified in config")
        else:
            if isinstance(version_dict, dict):
                self.version_dict = version_dict
            elif isinstance(version_dict, str) and version_dict == "load":
                if self.version_dict_exists:
                    self.load_version_dict()
            else:
                raise Exception("No version dict specified in config")

        if not os.path.exists(self.path):
            os.makedirs(self.path)

        if sv_mapping is not None:
            self.apply_mergelist(sv_mapping)

    @property
    def type(self):
        return "ssv"

    @property
    def scaling(self):
        return self._scaling

    @property
    def working_dir(self):
        return self._working_dir

    @property
    def config(self):
        if self._config is None:
            self._config = parser.Config(self.working_dir)
        return self._config

    @property
    def path(self):
        return "%s/ssv_%s/" % (self._working_dir, self.version)

    @property
    def version(self):
        return str(self._version)

    @property
    def version_dict_path(self):
        return self.path + "/version_dict.pkl"

    @property
    def mapping_dict_exists(self):
        return os.path.exists(self.mapping_dict_path)

    @property
    def reversed_mapping_dict_exists(self):
        return os.path.exists(self.reversed_mapping_dict_path)

    @property
    def mapping_dict_path(self):
        return self.path + "/mapping_dict.pkl"

    @property
    def reversed_mapping_dict_path(self):
        return self.path + "/reversed_mapping_dict.pkl"

    @property
    def id_changer_path(self):
        return self.path + "/id_changer.npy"

    @property
    def version_dict_exists(self):
        return os.path.exists(self.version_dict_path)

    @property
    def id_changer_exists(self):
        return os.path.exists(self.id_changer_path)

    @property
    def ssv_ids(self):
        if self._ssv_ids is None:
            if len(self.mapping_dict) > 0:
                return self.mapping_dict.keys()
            elif len(self.ssv_dict) > 0:
                return self.ssv_dict.keys()
            elif self.mapping_dict_exists:
                self.load_mapping_dict()
                return self.mapping_dict.keys()
            elif os.path.exists(self.path + "/ids.npy"):
                self._ssv_ids = np.load(self.path + "/ids.npy")
                return self._ssv_ids
            else:
                paths = glob.glob(self.path + "/so_storage/*/*/*/")
                self._ssv_ids = np.array([int(os.path.basename(p.strip("/")))
                                          for p in paths], dtype=np.int)
                return self._ssv_ids
        else:
            return self._ssv_ids

    @property
    def ssvs(self):
        ix = 0
        tot_nb_ssvs = len(self.ssv_ids)
        while ix < tot_nb_ssvs:
            yield self.get_super_segmentation_object(self.ssv_ids[ix])
            ix += 1

    @property
    def id_changer(self):
        if len(self._id_changer) == 0:
            self.load_id_changer()
        return self._id_changer

    def load_cached_data(self, name):
        if os.path.exists(self.path + name + "s.npy"):
            return np.load(self.path + name + "s.npy")

    def sv_id_to_ssv_id(self, sv_id):
        return self.id_changer[sv_id]

    def get_segmentationdataset(self, obj_type):
        assert obj_type in self.version_dict
        return segmentation.SegmentationDataset(obj_type,
                                                version=self.version_dict[
                                                    obj_type],
                                                working_dir=self.working_dir)

    def apply_mergelist(self, sv_mapping):
        assemble_from_mergelist(self, sv_mapping)

    def get_super_segmentation_object(self, obj_id, new_mapping=False,
                                      caching=True, create=False):
        if new_mapping:
            sso = SuperSegmentationObject(obj_id,
                                          self.version,
                                          self.version_dict,
                                          self.working_dir,
                                          create=create,
                                          sv_ids=self.mapping_dict[obj_id],
                                          scaling=self.scaling,
                                          object_caching=caching,
                                          voxel_caching=caching,
                                          mesh_cashing=caching,
                                          view_caching=caching)
        else:
            sso = SuperSegmentationObject(obj_id,
                                          self.version,
                                          self.version_dict,
                                          self.working_dir,
                                          create=create,
                                          scaling=self.scaling,
                                          object_caching=caching,
                                          voxel_caching=caching,
                                          mesh_cashing=caching,
                                          view_caching=caching)
        return sso

    def save_dataset_shallow(self):
        self.save_version_dict()
        self.save_mapping_dict()
        self.save_id_changer()

    # def save_dataset_deep(self, extract_only=False, attr_keys=(), stride=1000,
    #                       qsub_pe=None, qsub_queue=None, nb_cpus=1,
    #                       n_max_co_processes=None):
    #     ssd.save_dataset_deep(self, extract_only=extract_only,
    #                                       attr_keys=attr_keys, stride=stride,
    #                                       qsub_pe=qsub_pe, qsub_queue=qsub_queue,
    #                                       nb_cpus=nb_cpus,
    #                                       n_max_co_processes=n_max_co_processes)

    # def export_to_knossosdataset(self, kd, stride=1000, qsub_pe=None,
    #                              qsub_queue=None, nb_cpus=10):
    #     ssd.export_to_knossosdataset(self, kd, stride=stride, qsub_pe=qsub_pe,
    #                                              qsub_queue=qsub_queue, nb_cpus=nb_cpus)

    # def convert_knossosdataset(self, sv_kd_path, ssv_kd_path,
    #                            stride=256, qsub_pe=None, qsub_queue=None,
    #                            nb_cpus=None):
    #     ssd.convert_knossosdataset(self, sv_kd_path, ssv_kd_path,
    #                                            stride=stride, qsub_pe=qsub_pe,
    #                                            qsub_queue=qsub_queue, nb_cpus=nb_cpus)

    # def aggregate_segmentation_object_mappings(self, obj_types,
    #                                            stride=1000, qsub_pe=None,
    #                                            qsub_queue=None, nb_cpus=1):
    #     ssd.aggregate_segmentation_object_mappings(self, obj_types,
    #                                               stride=stride,
    #                                               qsub_pe=qsub_pe,
    #                                               qsub_queue=qsub_queue,
    #                                               nb_cpus=nb_cpus)

    # def apply_mapping_decisions(self, obj_types, stride=1000, qsub_pe=None,
    #                             qsub_queue=None, nb_cpus=1):
    #     ssd.apply_mapping_decisions(self, obj_types, stride=stride,
    #                                qsub_pe=qsub_pe, qsub_queue=qsub_pe,
    #                                nb_cpus=nb_cpus)

    def reskeletonize_objects(self, stride=200, small=True, big=True,
                              qsub_pe=None, qsub_queue=None, nb_cpus=1,
                              n_max_co_processes=None):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             range(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir])

        if small:
            if qsub_pe is None and qsub_queue is None:
                results = sm.start_multiprocess(
                    reskeletonize_objects_small_ones_thread,
                    multi_params, nb_cpus=nb_cpus)

            elif qu.__QSUB__:
                path_to_out = qu.QSUB_script(multi_params,
                                             "reskeletonize_objects_small_ones",
                                             n_cores=nb_cpus,
                                             pe=qsub_pe, queue=qsub_queue,
                                             script_folder=script_folder,
                                             n_max_co_processes=
                                             n_max_co_processes)
            else:
                raise Exception("QSUB not available")

        if big:
            if qsub_pe is None and qsub_queue is None:
                results = sm.start_multiprocess(
                    reskeletonize_objects_big_ones_thread,
                    multi_params, nb_cpus=1)

            elif qu.__QSUB__:
                path_to_out = qu.QSUB_script(multi_params,
                                             "reskeletonize_objects_big_ones",
                                             n_cores=10,
                                             n_max_co_processes=int(n_max_co_processes/10*nb_cpus),
                                             pe=qsub_pe, queue=qsub_queue,
                                             script_folder=script_folder)
            else:
                raise Exception("QSUB not available")

    def export_skeletons(self, obj_types, apply_mapping=True, stride=1000,
                         qsub_pe=None, qsub_queue=None, nb_cpus=1):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             xrange(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir, obj_types, apply_mapping])

        if qsub_pe is None and qsub_queue is None:
            results = sm.start_multiprocess(
                reskeletonize_objects_small_ones_thread,
                multi_params, nb_cpus=nb_cpus)
            no_skel_cnt = np.sum(results)

        elif qu.__QSUB__:
            path_to_out = qu.QSUB_script(multi_params,
                                         "export_skeletons",
                                         n_cores=nb_cpus,
                                         pe=qsub_pe, queue=qsub_queue,
                                         script_folder=script_folder)
            out_files = glob.glob(path_to_out + "/*")
            no_skel_cnt = 0
            for out_file in out_files:
                with open(out_file) as f:
                    no_skel_cnt += np.sum(pkl.load(f))

        else:
            raise Exception("QSUB not available")

        print "N no skeletons: %d" % no_skel_cnt

    def associate_objs_with_skel_nodes(self, obj_types, stride=1000,
                                       qsub_pe=None, qsub_queue=None,
                                       nb_cpus=1):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             xrange(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir, obj_types])

        if qsub_pe is None and qsub_queue is None:
            results = sm.start_multiprocess(
                associate_objs_with_skel_nodes_thread,
                multi_params, nb_cpus=nb_cpus)
            no_skel_cnt = np.sum(results)

        elif qu.__QSUB__:
            path_to_out = qu.QSUB_script(multi_params,
                                         "associate_objs_with_skel_nodes",
                                         n_cores=nb_cpus,
                                         pe=qsub_pe, queue=qsub_queue,
                                         script_folder=script_folder)
        else:
            raise Exception("QSUB not available")

    def predict_axoness(self, stride=1000, qsub_pe=None, qsub_queue=None,
                        nb_cpus=1):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             xrange(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir])

        if qsub_pe is None and qsub_queue is None:
            results = sm.start_multiprocess(
                predict_axoness_thread,
                multi_params, nb_cpus=nb_cpus)

        elif qu.__QSUB__:
            path_to_out = qu.QSUB_script(multi_params,
                                         "predict_axoness",
                                         n_cores=nb_cpus,
                                         pe=qsub_pe, queue=qsub_queue,
                                         script_folder=script_folder)
        else:
            raise Exception("QSUB not available")

    def predict_cell_types(self, stride=1000, qsub_pe=None, qsub_queue=None,
                           nb_cpus=1):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             xrange(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir])

        if qsub_pe is None and qsub_queue is None:
            results = sm.start_multiprocess(
                predict_cell_type_thread,
                multi_params, nb_cpus=nb_cpus)

        elif qu.__QSUB__:
            path_to_out = qu.QSUB_script(multi_params,
                                         "predict_cell_type",
                                         n_cores=nb_cpus,
                                         pe=qsub_pe, queue=qsub_queue,
                                         script_folder=script_folder)
        else:
            raise Exception("QSUB not available")

    def save_version_dict(self):
        if len(self.version_dict) > 0:
            write_obj2pkl(self.version_dict_path, self.version_dict)

    def load_version_dict(self):
        assert self.version_dict_exists
        self.version_dict = load_pkl2obj(self.version_dict_path)

    def save_mapping_dict(self):
        if len(self.mapping_dict) > 0:
            write_obj2pkl(self.mapping_dict_path, self.mapping_dict)

    def save_reversed_mapping_dict(self):
        if len(self.reversed_mapping_dict) > 0:
            write_obj2pkl(self.reversed_mapping_dict_path,
                          self.reversed_mapping_dict)

    def load_mapping_dict(self):
        assert self.mapping_dict_exists
        self.mapping_dict = load_pkl2obj(self.mapping_dict_path)

    def load_reversed_mapping_dict(self):
        assert self.reversed_mapping_dict_exists
        self.reversed_mapping_dict = load_pkl2obj(self.reversed_mapping_dict_path)

    def save_id_changer(self):
        if len(self._id_changer) > 0:
            np.save(self.id_changer_path, self._id_changer)

    def load_id_changer(self):
        assert self.id_changer_exists
        self._id_changer = np.load(self.id_changer_path)


# UTILITIES

def aggregate_segmentation_object_mappings(ssd, obj_types,
                                           stride=1000, qsub_pe=None,
                                           qsub_queue=None, nb_cpus=1):
    for obj_type in obj_types:
        assert obj_type in ssd.version_dict
    assert "sv" in ssd.version_dict

    multi_params = []
    for ssv_id_block in [ssd.ssv_ids[i:i + stride]
                         for i in
                         range(0, len(ssd.ssv_ids), stride)]:
        multi_params.append([ssv_id_block, ssd.version, ssd.version_dict,
                             ssd.working_dir, obj_types])

    if qsub_pe is None and qsub_queue is None:
        results = sm.start_multiprocess(
            _aggregate_segmentation_object_mappings_thread,
            multi_params, nb_cpus=nb_cpus)

    elif qu.__QSUB__:
        path_to_out = qu.QSUB_script(multi_params,
                                     "aggregate_segmentation_object_mappings",
                                     pe=qsub_pe, queue=qsub_queue,
                                     script_folder=script_folder)

    else:
        raise Exception("QSUB not available")


def _aggregate_segmentation_object_mappings_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    obj_types = args[4]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id, True)
        mappings = dict((obj_type, Counter()) for obj_type in obj_types)

        for sv in ssv.svs:
            sv.load_attr_dict()
            for obj_type in obj_types:
                if "mapping_%s_ids" % obj_type in sv.attr_dict:
                    keys = sv.attr_dict["mapping_%s_ids" % obj_type]
                    values = sv.attr_dict["mapping_%s_ratios" % obj_type]
                    mappings[obj_type] += Counter(dict(zip(keys, values)))

        ssv.load_attr_dict()
        for obj_type in obj_types:
            if obj_type in mappings:
                ssv.attr_dict["mapping_%s_ids" % obj_type] = \
                    mappings[obj_type].keys()
                ssv.attr_dict["mapping_%s_ratios" % obj_type] = \
                    mappings[obj_type].values()

        ssv.save_attr_dict()


def apply_mapping_decisions(ssd, obj_types, stride=1000, qsub_pe=None,
                            qsub_queue=None, nb_cpus=1):
    for obj_type in obj_types:
        assert obj_type in ssd.version_dict

    multi_params = []
    for ssv_id_block in [ssd.ssv_ids[i:i + stride]
                         for i in
                         range(0, len(ssd.ssv_ids), stride)]:
        multi_params.append([ssv_id_block, ssd.version, ssd.version_dict,
                             ssd.working_dir, obj_types])

    if qsub_pe is None and qsub_queue is None:
        results = sm.start_multiprocess(_apply_mapping_decisions_thread,
                                        multi_params, nb_cpus=nb_cpus)

    elif qu.__QSUB__:
        path_to_out = qu.QSUB_script(multi_params,
                                     "apply_mapping_decisions",
                                     pe=qsub_pe, queue=qsub_queue,
                                     script_folder=script_folder)

    else:
        raise Exception("QSUB not available")


def _apply_mapping_decisions_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    obj_types = args[4]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id, True)
        for obj_type in obj_types:
            if obj_type == "sj":
                correct_for_background = True
            else:
                correct_for_background = False

            ssv.apply_mapping_decision(obj_type,
                                       correct_for_background=correct_for_background,
                                       save=True)


def save_dataset_deep(ssd, extract_only=False, attr_keys=(), stride=1000,
                      qsub_pe=None, qsub_queue=None, nb_cpus=1,
                      n_max_co_processes=None):
    ssd.save_dataset_shallow()

    multi_params = []
    for ssv_id_block in [ssd.ssv_ids[i:i + stride]
                         for i in range(0, len(ssd.ssv_ids), stride)]:
        multi_params.append([ssv_id_block, ssd.version, ssd.version_dict,
                             ssd.working_dir, extract_only, attr_keys])

    if qsub_pe is None and qsub_queue is None:
        results = sm.start_multiprocess(
            _write_super_segmentation_dataset_thread,
            multi_params, nb_cpus=nb_cpus)

    elif qu.__QSUB__:
        path_to_out = qu.QSUB_script(multi_params,
                                     "write_super_segmentation_dataset",
                                     pe=qsub_pe, queue=qsub_queue,
                                     script_folder=script_folder,
                                     n_cores=nb_cpus,
                                     n_max_co_processes=n_max_co_processes)

        out_files = glob.glob(path_to_out + "/*")
        results = []
        for out_file in out_files:
            with open(out_file) as f:
                results.append(pkl.load(f))
    else:
        raise Exception("QSUB not available")

    attr_dict = {}
    for this_attr_dict in results:
        for attribute in this_attr_dict.keys():
            if not attribute in attr_dict:
                attr_dict[attribute] = []

            attr_dict[attribute] += this_attr_dict[attribute]

    if not ssd.mapping_dict_exists:
        ssd.mapping_dict = dict(zip(attr_dict["id"], attr_dict["sv"]))
        ssd.save_dataset_shallow()

    for attribute in attr_dict.keys():
        if extract_only:
            np.save(ssd.path + "/%ss_sel.npy" % attribute,
                    attr_dict[attribute])
        else:
            np.save(ssd.path + "/%ss.npy" % attribute,
                    attr_dict[attribute])


def _write_super_segmentation_dataset_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    extract_only = args[4]
    attr_keys = args[5]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    try:
        ssd.load_mapping_dict()
        mapping_dict_avail = True
    except:
        mapping_dict_avail = False

    attr_dict = dict(id=[])

    for ssv_obj_id in ssv_obj_ids:
        print(ssv_obj_id)
        ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id,
                                                    new_mapping=True,
                                                    create=True)

        if ssv_obj.attr_dict_exists:
            ssv_obj.load_attr_dict()

        if not extract_only:

            if len(ssv_obj.attr_dict["sv"]) == 0:
                if mapping_dict_avail:
                    ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id, True)

                    if ssv_obj.attr_dict_exists:
                        ssv_obj.load_attr_dict()
                else:
                    raise Exception("No mapping information found")
        if not extract_only:
            if "rep_coord" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["rep_coord"] = ssv_obj.rep_coord
            if "bounding_box" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["bounding_box"] = ssv_obj.bounding_box
            if "size" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["size"] = ssv_obj.size

        ssv_obj.attr_dict["sv"] = np.array(ssv_obj.attr_dict["sv"],
                                           dtype=np.int)

        if extract_only:
            ignore = False
            for attribute in attr_keys:
                if not attribute in ssv_obj.attr_dict:
                    ignore = True
                    break
            if ignore:
                continue

            attr_dict["id"].append(ssv_obj_id)

            for attribute in attr_keys:
                if attribute not in attr_dict:
                    attr_dict[attribute] = []

                if attribute in ssv_obj.attr_dict:
                    attr_dict[attribute].append(ssv_obj.attr_dict[attribute])
                else:
                    attr_dict[attribute].append(None)
        else:
            attr_dict["id"].append(ssv_obj_id)
            for attribute in ssv_obj.attr_dict.keys():
                if attribute not in attr_dict:
                    attr_dict[attribute] = []

                attr_dict[attribute].append(ssv_obj.attr_dict[attribute])

                ssv_obj.save_attr_dict()

    return attr_dict


def export_to_knossosdataset(ssd, kd, stride=1000, qsub_pe=None,
                             qsub_queue=None, nb_cpus=10):
    multi_params = []
    for ssv_id_block in [ssd.ssv_ids[i:i + stride]
                         for i in range(0, len(ssd.ssv_ids), stride)]:
        multi_params.append([ssv_id_block, ssd.version, ssd.version_dict,
                             ssd.working_dir, kd.knossos_path, nb_cpus])

    if qsub_pe is None and qsub_queue is None:
        results = sm.start_multiprocess(_export_to_knossosdataset_thread,
                                        multi_params, nb_cpus=nb_cpus)

    elif qu.__QSUB__:
        path_to_out = qu.QSUB_script(multi_params,
                                     "export_to_knossosdataset",
                                     pe=qsub_pe, queue=qsub_queue,
                                     script_folder=script_folder)

    else:
        raise Exception("QSUB not available")


def _export_to_knossosdataset_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    kd_path = args[4]
    nb_threads = args[5]

    kd = knossosdataset.KnossosDataset().initialize_from_knossos_path(kd_path)

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_obj_id in ssv_obj_ids:
        print(ssv_obj_id)

        ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id, True)

        offset = ssv_obj.bounding_box[0]
        if not 0 in offset:
            kd.from_matrix_to_cubes(ssv_obj.bounding_booffset,
                                    data=ssv_obj.voxels.astype(np.uint32) *
                                         ssv_obj_id,
                                    overwrite=False,
                                    nb_threads=nb_threads)


def convert_knossosdataset(ssd, sv_kd_path, ssv_kd_path,
                           stride=256, qsub_pe=None, qsub_queue=None,
                           nb_cpus=None):
    ssd.save_dataset_shallow()
    sv_kd = knossosdataset.KnossosDataset()
    sv_kd.initialize_from_knossos_path(sv_kd_path)

    if not os.path.exists(ssv_kd_path):
        ssv_kd = knossosdataset.KnossosDataset()
        ssv_kd.initialize_without_conf(ssv_kd_path, sv_kd.boundary,
                                       sv_kd.scale,
                                       sv_kd.experiment_name,
                                       mags=[1])

    size = np.ones(3, dtype=np.int) * stride
    multi_params = []
    offsets = []
    for x in range(0, sv_kd.boundary[0], stride):
        for y in range(0, sv_kd.boundary[1], stride):
            for z in range(0, sv_kd.boundary[2], stride):
                offsets.append([x, y, z])
                if len(offsets) >= 20:
                    multi_params.append([ssd.version, ssd.version_dict,
                                         ssd.working_dir, nb_cpus,
                                         sv_kd_path, ssv_kd_path, offsets,
                                         size])
                    offsets = []

    if len(offsets) > 0:
        multi_params.append([ssd.version, ssd.version_dict,
                             ssd.working_dir, nb_cpus,
                             sv_kd_path, ssv_kd_path, offsets,
                             size])

    if qsub_pe is None and qsub_queue is None:
        results = sm.start_multiprocess(_convert_knossosdataset_thread,
                                        multi_params, nb_cpus=nb_cpus)

    elif qu.__QSUB__:
        path_to_out = qu.QSUB_script(multi_params,
                                     "convert_knossosdataset",
                                     pe=qsub_pe, queue=qsub_queue,
                                     script_folder=script_folder)

    else:
        raise Exception("QSUB not available")


def _convert_knossosdataset_thread(args):
    version = args[0]
    version_dict = args[1]
    working_dir = args[2]
    nb_threads = args[3]
    sv_kd_path = args[4]
    ssv_kd_path = args[5]
    offsets = args[6]
    size = args[7]

    sv_kd = knossosdataset.KnossosDataset()
    sv_kd.initialize_from_knossos_path(sv_kd_path)
    ssv_kd = knossosdataset.KnossosDataset()
    ssv_kd.initialize_from_knossos_path(ssv_kd_path)

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_id_changer()

    for offset in offsets:
        block = sv_kd.from_overlaycubes_to_matrix(size, offset,
                                                  datatype=np.uint32,
                                                  nb_threads=nb_threads)

        block = ssd.id_changer[block]

        ssv_kd.from_matrix_to_cubes(offset,
                                    data=block.astype(np.uint32),
                                    datatype=np.uint32,
                                    overwrite=False,
                                    nb_threads=nb_threads)

        raw = sv_kd.from_raw_cubes_to_matrix(size, offset,
                                             nb_threads=nb_threads)

        ssv_kd.from_matrix_to_cubes(offset,
                                    data=raw,
                                    datatype=np.uint8,
                                    as_raw=True,
                                    overwrite=False,
                                    nb_threads=nb_threads)


def export_skeletons(ssd, obj_types, apply_mapping=True, stride=1000,
                     qsub_pe=None, qsub_queue=None, nb_cpus=1):
    multi_params = []
    for ssv_id_block in [ssd.ssv_ids[i:i + stride]
                         for i in
                         range(0, len(ssd.ssv_ids), stride)]:
        multi_params.append([ssv_id_block, ssd.version, ssd.version_dict,
                             ssd.working_dir, obj_types, apply_mapping])
    # TODO @Sven: which function is requiered here? I changed it from _export_skeletons to ssh.export_skeletons
    if qsub_pe is None and qsub_queue is None:
        results = sm.start_multiprocess(
            export_skeletons_thread,
            multi_params, nb_cpus=nb_cpus)
        no_skel_cnt = np.sum(results)

    elif qu.__QSUB__:
        path_to_out = qu.QSUB_script(multi_params,
                                     "export_skeletons",
                                     n_cores=nb_cpus,
                                     pe=qsub_pe, queue=qsub_queue,
                                     script_folder=script_folder)
        out_files = glob.glob(path_to_out + "/*")
        no_skel_cnt = 0
        for out_file in out_files:
            with open(out_file) as f:
                no_skel_cnt += np.sum(pkl.load(f))

    else:
        raise Exception("QSUB not available")

    print("N no skeletons: %d" % no_skel_cnt)


def load_voxels_downsampled(sso, downsampling=(2, 2, 1), nb_threads=10):
    def _load_sv_voxels_thread(args):
        sv_id = args[0]
        sv = segmentation.SegmentationObject(sv_id,
                                             obj_type="sv",
                                             version=sso.version_dict[
                                                 "sv"],
                                             working_dir=sso.working_dir,
                                             config=sso.config,
                                             voxel_caching=False)
        if sv.voxels_exist:
            box = [np.array(sv.bounding_box[0] - sso.bounding_box[0],
                            dtype=np.int)]

            box[0] /= downsampling
            size = np.array(sv.bounding_box[1] -
                            sv.bounding_box[0], dtype=np.float)
            size = np.ceil(size.astype(np.float) /
                           downsampling).astype(np.int)

            box.append(box[0] + size)

            sv_voxels = sv.voxels
            if not isinstance(sv_voxels, int):
                sv_voxels = sv_voxels[::downsampling[0],
                            ::downsampling[1],
                            ::downsampling[2]]

                voxels[box[0][0]: box[1][0],
                box[0][1]: box[1][1],
                box[0][2]: box[1][2]][sv_voxels] = True

    downsampling = np.array(downsampling, dtype=np.int)

    if len(sso.sv_ids) == 0:
        return None

    voxel_box_size = sso.bounding_box[1] - sso.bounding_box[0]
    voxel_box_size = voxel_box_size.astype(np.float)

    voxel_box_size = np.ceil(voxel_box_size / downsampling).astype(np.int)

    voxels = np.zeros(voxel_box_size, dtype=np.bool)

    multi_params = []
    for sv_id in sso.sv_ids:
        multi_params.append([sv_id])

    if nb_threads > 1:
        pool = ThreadPool(nb_threads)
        pool.map(_load_sv_voxels_thread, multi_params)
        pool.close()
        pool.join()
    else:
        map(_load_sv_voxels_thread, multi_params)

    return voxels


def associate_objs_with_skel_nodes_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    obj_types = args[4]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)
        ssv.load_skeleton()
        if len(ssv.skeleton["nodes"]) > 0:
            ssv.associate_objs_with_skel_nodes(obj_types)


def predict_axoness_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)

        if not ssv.load_skeleton():
            continue

        ssv.load_attr_dict()
        if "assoc_sj" in ssv.attr_dict:
            ssv.predict_axoness(feature_context_nm=5000, clf_name="rfc")
        elif len(ssv.skeleton["nodes"]) > 0:
            try:
                ssv.associate_objs_with_skel_nodes(("sj", "mi", "vc"))
                ssv.predict_axoness(feature_context_nm=5000, clf_name="rfc")
            except:
                pass


def predict_cell_type_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)

        if not ssv.load_skeleton():
            continue

        ssv.load_attr_dict()
        if "assoc_sj" in ssv.attr_dict:
            ssv.predict_cell_type(feature_context_nm=25000, clf_name="rfc")
        elif len(ssv.skeleton["nodes"]) > 0:
            try:
                ssv.associate_objs_with_skel_nodes(("sj", "mi", "vc"))
                ssv.predict_cell_type(feature_context_nm=25000, clf_name="rfc")
            except:
                pass


def export_skeletons_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    obj_types = args[4]
    apply_mapping = args[5]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    no_skel_cnt = 0
    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)

        try:
            ssv.load_skeleton()
            skeleton_avail = True
        except:
            skeleton_avail = False
            no_skel_cnt += 1

        if not skeleton_avail:
            continue

        if ssv.size == 0:
            continue

        if len(ssv.skeleton["nodes"]) == 0:
            continue

        try:
            ssv.save_skeleton_to_kzip()

            for obj_type in obj_types:
                if apply_mapping:
                    if obj_type == "sj":
                        correct_for_background = True
                    else:
                        correct_for_background = False
                    ssv.apply_mapping_decision(obj_type,
                                               correct_for_background=correct_for_background)

            ssv.save_objects_to_kzip_sparse(obj_types)

        except:
            pass

    return no_skel_cnt


def export_to_knossosdataset_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    kd_path = args[4]
    nb_threads = args[5]

    kd = knossosdataset.KnossosDataset().initialize_from_knossos_path(kd_path)

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_obj_id in ssv_obj_ids:
        print ssv_obj_id

        ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id, True)

        offset = ssv_obj.bounding_box[0]
        if not 0 in offset:
            kd.from_matrix_to_cubes(ssv_obj.bounding_booffset,
                                    data=ssv_obj.voxels.astype(np.uint32) *
                                         ssv_obj_id,
                                    overwrite=False,
                                    nb_threads=nb_threads)


def convert_knossosdataset_thread(args):
    version = args[0]
    version_dict = args[1]
    working_dir = args[2]
    nb_threads = args[3]
    sv_kd_path = args[4]
    ssv_kd_path = args[5]
    offsets = args[6]
    size = args[7]

    sv_kd = knossosdataset.KnossosDataset()
    sv_kd.initialize_from_knossos_path(sv_kd_path)
    ssv_kd = knossosdataset.KnossosDataset()
    ssv_kd.initialize_from_knossos_path(ssv_kd_path)

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_id_changer()

    for offset in offsets:
        block = sv_kd.from_overlaycubes_to_matrix(size, offset,
                                                  datatype=np.uint32,
                                                  nb_threads=nb_threads)

        block = ssd.id_changer[block]

        ssv_kd.from_matrix_to_cubes(offset,
                                    data=block.astype(np.uint32),
                                    datatype=np.uint32,
                                    overwrite=False,
                                    nb_threads=nb_threads)

        raw = sv_kd.from_raw_cubes_to_matrix(size, offset,
                                             nb_threads=nb_threads)

        ssv_kd.from_matrix_to_cubes(offset,
                                    data=raw,
                                    datatype=np.uint8,
                                    as_raw=True,
                                    overwrite=False,
                                    nb_threads=nb_threads)


def aggregate_segmentation_object_mappings_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    obj_types = args[4]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id, True)
        mappings = dict((obj_type, Counter()) for obj_type in obj_types)

        for sv in ssv.svs:
            sv.load_attr_dict()
            for obj_type in obj_types:
                if "mapping_%s_ids" % obj_type in sv.attr_dict:
                    keys = sv.attr_dict["mapping_%s_ids" % obj_type]
                    values = sv.attr_dict["mapping_%s_ratios" % obj_type]
                    mappings[obj_type] += Counter(dict(zip(keys, values)))

        ssv.load_attr_dict()
        for obj_type in obj_types:
            if obj_type in mappings:
                ssv.attr_dict["mapping_%s_ids" % obj_type] = \
                    mappings[obj_type].keys()
                ssv.attr_dict["mapping_%s_ratios" % obj_type] = \
                    mappings[obj_type].values()

        ssv.save_attr_dict()


def apply_mapping_decisions_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    obj_types = args[4]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id, True)
        for obj_type in obj_types:
            if obj_type == "sj":
                correct_for_background = True
            else:
                correct_for_background = False

            ssv.apply_mapping_decision(obj_type,
                                       correct_for_background=correct_for_background,
                                       save=True)


def reskeletonize_objects_small_ones_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_id in ssv_obj_ids:
        print "------------", ssv_id
        ssv = ssd.get_super_segmentation_object(ssv_id, True)
        if np.product(ssv.shape) > 1e10:
            continue
        # elif np.product(ssv.shape) > 10**3:
        #     ssv.calculate_skeleton(coord_scaling=(8, 8, 4))
        elif ssv.size > 0:
            ssv.calculate_skeleton(coord_scaling=(8, 8, 4), plain=True)
        else:
            ssv.skeleton = {"nodes": [], "edges": [], "diameters": []}
        ssv.save_skeleton()
        ssv.clear_cache()


def reskeletonize_objects_big_ones_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id, True)
        if np.product(ssv.shape) > 1e10:
            ssv.calculate_skeleton(coord_scaling=(10, 10, 5), plain=True)
        else:
            continue
        ssv.save_skeleton()
        ssv.clear_cache()


def write_super_segmentation_dataset_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    extract_only = args[4]
    attr_keys = args[5]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    try:
        ssd.load_mapping_dict()
        mapping_dict_avail = True
    except:
        mapping_dict_avail = False

    attr_dict = dict(id=[])

    for ssv_obj_id in ssv_obj_ids:
        print ssv_obj_id
        ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id,
                                                    new_mapping=True,
                                                    create=True)

        if ssv_obj.attr_dict_exists:
            ssv_obj.load_attr_dict()

        if not extract_only:

            if len(ssv_obj.attr_dict["sv"]) == 0:
                if mapping_dict_avail:
                    ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id, True)

                    if ssv_obj.attr_dict_exists:
                        ssv_obj.load_attr_dict()
                else:
                    raise Exception("No mapping information found")
        if not extract_only:
            if "rep_coord" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["rep_coord"] = ssv_obj.rep_coord
            if "bounding_box" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["bounding_box"] = ssv_obj.bounding_box
            if "size" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["size"] = ssv_obj.size

        ssv_obj.attr_dict["sv"] = np.array(ssv_obj.attr_dict["sv"],
                                           dtype=np.int)

        if extract_only:
            ignore = False
            for attribute in attr_keys:
                if not attribute in ssv_obj.attr_dict:
                    ignore = True
                    break
            if ignore:
                continue

            attr_dict["id"].append(ssv_obj_id)

            for attribute in attr_keys:
                if attribute not in attr_dict:
                    attr_dict[attribute] = []

                if attribute in ssv_obj.attr_dict:
                    attr_dict[attribute].append(ssv_obj.attr_dict[attribute])
                else:
                    attr_dict[attribute].append(None)
        else:
            attr_dict["id"].append(ssv_obj_id)
            for attribute in ssv_obj.attr_dict.keys():
                if attribute not in attr_dict:
                    attr_dict[attribute] = []

                attr_dict[attribute].append(ssv_obj.attr_dict[attribute])

                ssv_obj.save_attr_dict()

    return attr_dict