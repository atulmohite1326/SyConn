import cPickle as pkl
import glob
import numpy as np
import os
import scipy.ndimage
from ..utils import datahandler, basics

from syconnfs.representations import segmentation
from syconnmp import qsub_utils as qu
from syconnmp import shared_mem as sm

from knossos_utils import chunky, knossosdataset

script_folder = os.path.abspath(os.path.dirname(__file__) + "/QSUB_scripts/")


def find_contact_sites(cset, knossos_path, filename, n_max_co_processes=None,
                       qsub_pe=None, qsub_queue=None):
    multi_params = []
    for chunk in cset.chunk_dict.values():
        multi_params.append([chunk, knossos_path, filename])

    if qsub_pe is None and qsub_queue is None:
        results = sm.start_multiprocess(_contact_site_detection_thread,
                                        multi_params, debug=True)
    elif qu.__QSUB__:
        path_to_out = qu.QSUB_script(multi_params,
                                     "contact_site_detection",
                                     script_folder=script_folder,
                                     n_max_co_processes=n_max_co_processes,
                                     pe=qsub_pe, queue=qsub_queue)

        out_files = glob.glob(path_to_out + "/*")
        results = []
        for out_file in out_files:
            with open(out_file) as f:
                results.append(pkl.load(f))
    else:
        raise Exception("QSUB not available")


def extract_contact_sites(cset, filename, working_dir, stride=10,
                          n_max_co_processes=None, qsub_pe=None, qsub_queue=None):
    segdataset = segmentation.SegmentationDataset("cs_pre",
                                                  version="new",
                                                  working_dir=working_dir,
                                                  create=True)

    multi_params = []
    chunks = cset.chunk_dict.values()
    for chunk_block in [chunks[i: i + stride]
                        for i in xrange(0, len(chunks), stride)]:
        multi_params.append([chunk_block, working_dir, filename,
                             segdataset.version])

    if qsub_pe is None and qsub_queue is None:
        results = sm.start_multiprocess(_extract_pre_cs_thread,
                                        multi_params, debug=False)
    elif qu.__QSUB__:
        path_to_out = qu.QSUB_script(multi_params,
                                     "extract_pre_cs",
                                     script_folder=script_folder,
                                     n_max_co_processes=n_max_co_processes,
                                     pe=qsub_pe, queue=qsub_queue)
    else:
        raise Exception("QSUB not available")


def _contact_site_detection_thread(args):
    chunk = args[0]
    knossos_path = args[1]
    filename = args[2]

    kd = knossosdataset.KnossosDataset()
    kd.initialize_from_knossos_path(knossos_path)

    overlap = np.array([6, 6, 3], dtype=np.int)
    offset = np.array(chunk.coordinates - overlap)
    size = 2 * overlap + np.array(chunk.size)
    data = kd.from_overlaycubes_to_matrix(size, offset, datatype=np.uint64).astype(np.uint32)

    contacts = detect_cs(data)

    datahandler.save_to_h5py([contacts],
                             chunk.folder + filename +
                             ".h5", ["cs"])


def detect_cs(arr):
    jac = np.zeros([3, 3, 3], dtype=np.int)
    jac[1, 1, 1] = -6
    jac[1, 1, 0] = 1
    jac[1, 1, 2] = 1
    jac[1, 0, 1] = 1
    jac[1, 2, 1] = 1
    jac[2, 1, 1] = 1
    jac[0, 1, 1] = 1

    edges = scipy.ndimage.convolve(arr.astype(np.int), jac) < 0

    edges = edges.astype(np.uint32)
    # edges[arr == 0] = True
    arr = arr.astype(np.uint32)

    # cs_seg = cse.process_chunk(edges, arr, [7, 7, 3])
    cs_seg = process_block_nonzero(edges, arr, [13, 13, 7])

    return cs_seg


def kernel(chunk, center_id):
    unique_ids, counts = np.unique(chunk, return_counts=True)

    counts[unique_ids == 0] = -1
    counts[unique_ids == center_id] = -1

    if np.max(counts) > 0:
        partner_id = unique_ids[np.argmax(counts)]

        if center_id > partner_id:
            return (partner_id << 32) + center_id
        else:
            return (center_id << 32) + partner_id
    else:
        return 0


def process_block(edges, arr, stencil=(7, 7, 3)):
    stencil = np.array(stencil, dtype=np.int)
    assert np.sum(stencil % 2) == 3

    out = np.zeros_like(arr, dtype=np.uint64)
    offset = stencil / 2
    for x in range(offset[0], arr.shape[0] - offset[0]):
        for y in range(offset[1], arr.shape[1] - offset[1]):
            for z in range(offset[2], arr.shape[2] - offset[2]):
                if edges[x, y, z] == 0:
                    continue

                center_id = arr[x, y, z]
                chunk = arr[x - offset[0]: x + offset[0] + 1, y - offset[1]: y + offset[1], z - offset[2]: z + offset[2]]
                out[x, y, z] = kernel(chunk, center_id)
    return out


def process_block_nonzero(edges, arr, stencil=(7, 7, 3)):
    stencil = np.array(stencil, dtype=np.int)
    assert np.sum(stencil % 2) == 3

    arr_shape = np.array(arr.shape)
    out = np.zeros(arr_shape - stencil + 1, dtype=np.uint64)
    offset = stencil / 2
    nze = np.nonzero(edges[offset[0]: -offset[0], offset[1]: -offset[1], offset[2]: -offset[2]])
    for x, y, z in zip(nze[0], nze[1], nze[2]):
        center_id = arr[x + offset[0], y + offset[1], z + offset[2]]
        chunk = arr[x: x + stencil[0], y: y + stencil[1], z: z + stencil[2]]
        out[x, y, z] = kernel(chunk, center_id)
    return out


def _extract_pre_cs_thread(args):
    chunk_block = args[0]
    working_dir = args[1]
    filename = args[2]
    version = args[3]

    segdataset = segmentation.SegmentationDataset("cs_pre",
                                                  version=version,
                                                  working_dir=working_dir)
    for chunk in chunk_block:
        path = chunk.folder + filename + ".h5"

        this_segmentation = datahandler.load_from_h5py(path, ["cs"])[0]

        unique_ids = np.unique(this_segmentation)
        for unique_id in unique_ids:
            if unique_id == 0:
                continue

            id_mask = this_segmentation == unique_id
            id_mask, in_chunk_offset = basics.crop_bool_array(id_mask)
            abs_offset = chunk.coordinates + np.array(in_chunk_offset)
            abs_offset = abs_offset.astype(np.int)
            segobj = segmentation.SegmentationObject(unique_id, "cs_pre",
                                                     version=segdataset.version,
                                                     working_dir=segdataset.working_dir,
                                                     create=True)
            segobj.save_voxels(id_mask, abs_offset)
            print unique_id